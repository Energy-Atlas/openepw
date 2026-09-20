"""Runtime-only settings; .env loading is explicit and never writes credentials."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import Field, SecretStr

from .models import Model


class RuntimeConfig(Model):
    data_root: Path = Path(".local/openepw")
    nlr_api_key: SecretStr | None = None
    nlr_email: SecretStr | None = None
    cds_key: SecretStr | None = None
    openmeteo_api_key: SecretStr | None = None
    bearer_token: SecretStr | None = None
    timeout: float = Field(default=60, gt=0, le=300)
    retries: int = Field(default=2, ge=0, le=5)
    max_response_bytes: int = Field(default=50_000_000, gt=0)
    max_climate_bytes: int = Field(default=500_000_000, gt=0)
    workers: int = Field(default=2, ge=1, le=8)

    @classmethod
    def load(
        cls,
        path: str | Path = "config.local.toml",
        *,
        env_file: str | Path | None = None,
        **overrides,
    ):
        values = {}
        path = Path(path)
        if path.is_file():
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
            for section in ("runtime", "credentials"):
                values.update(raw.get(section, {}))
        environment = {}
        if env_file and Path(env_file).is_file():
            for line in Path(env_file).read_text(encoding="utf-8-sig").splitlines():
                if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    environment[k.strip()] = v.strip().strip("\"'")
        environment.update(os.environ)
        for name in cls.model_fields:
            key = "OPENEPW_" + name.upper()
            if environment.get(key):
                values[name] = environment[key]
        values.update(overrides)
        return cls(**values)
