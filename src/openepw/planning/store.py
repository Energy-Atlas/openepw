"""Atomic, content-addressed local weather-plan references."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import ValidationError

from ..artifacts.store import atomic_write
from ..models import OpenEPWError, WeatherPlan

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MAX_PLAN_BYTES = 5_000_000


class PlanStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve() / "plans"

    def put(self, plan: WeatherPlan) -> str:
        checked = WeatherPlan.model_validate_json(plan.model_dump_json())
        if checked.kind != "weather":
            raise OpenEPWError("INVALID_REQUEST", "Only weather plans are stored in Stage 3a")
        body = checked.model_dump_json().encode("utf-8")
        if len(body) > _MAX_PLAN_BYTES:
            raise OpenEPWError("RESOURCE_LIMIT", "Plan exceeds local storage limit")
        atomic_write(self.root / f"{checked.plan_hash}.json", body)
        return checked.plan_hash

    def get(self, plan_hash: str) -> WeatherPlan:
        if not _HASH.fullmatch(plan_hash):
            raise OpenEPWError("PLAN_NOT_FOUND", "Invalid plan identifier")
        path = self.root / f"{plan_hash}.json"
        if not path.exists():
            raise OpenEPWError("PLAN_NOT_FOUND", "Unknown plan identifier")
        if not path.resolve().is_relative_to(self.root):
            raise OpenEPWError("PLAN_STALE", "Stored plan path is invalid")
        try:
            if path.stat().st_size > _MAX_PLAN_BYTES:
                raise ValueError("oversized plan")
            plan = WeatherPlan.model_validate_json(path.read_bytes())
            if plan.kind != "weather" or plan.plan_hash != plan_hash:
                raise ValueError("plan identity mismatch")
        except (OSError, ValueError, ValidationError) as error:
            raise OpenEPWError("PLAN_STALE", "Stored plan failed validation") from error
        return plan
