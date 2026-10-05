"""Submission needs the person's confirmation, asked through MCP elicitation.

A model-callable approval tool could approve itself, so none exists. The server asks the
client; the openepw host answers only for plans the person approved in a plan review, and
other clients show their own confirmation.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from mcp.server.elicitation import AcceptedElicitation
from mcp.server.fastmcp import Context
from mcp.types import ClientCapabilities, ElicitationCapability, ElicitResult
from pydantic import BaseModel, Field

from ..models import OpenEPWError

_PLAN = re.compile(r"\bplan ([0-9a-f]{64})\b")


class SubmitConfirmation(BaseModel):
    approve: bool = Field(description="Run this reviewed plan and start provider retrieval")


def confirmation_message(plan_hash: str) -> str:
    return (f"Approve and run reviewed weather plan {plan_hash}? "
            "This starts provider retrieval.")


def plan_hash_from_message(message: str) -> str | None:
    match = _PLAN.search(message or "")
    return match.group(1) if match else None


async def confirm_submission(ctx: Context, plan_hash: str) -> str:
    """Ask the client to confirm; returns how the submission was approved."""
    try:
        session = ctx.session
    except ValueError:                        # called outside a client request (direct call)
        session = None
    capable = session is not None and session.check_client_capability(
        ClientCapabilities(elicitation=ElicitationCapability()))
    if not capable:
        raise OpenEPWError("APPROVAL_REQUIRED",
                           "Submitting needs a client that can confirm the reviewed plan with the person")
    result = await ctx.elicit(confirmation_message(plan_hash), SubmitConfirmation)
    if not isinstance(result, AcceptedElicitation) or not result.data.approve:
        raise OpenEPWError("APPROVAL_DECLINED", "The plan was not approved; nothing was submitted")
    return "elicitation"


def approval_callback(is_approved: Callable[[str], bool]):
    """Client side: accept a confirmation only for a plan the person already approved."""

    async def callback(context: Any, params: Any) -> ElicitResult:
        plan_hash = plan_hash_from_message(getattr(params, "message", ""))
        if plan_hash and is_approved(plan_hash):
            return ElicitResult(action="accept", content={"approve": True})
        return ElicitResult(action="decline")

    return callback
