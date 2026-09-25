"""Optional local reference-agent command."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from .agent import AgentIntent, ReferenceAgent
from .mcp_client import MCPToolFailure, StdioMCPPort
from .model import ModelUnavailable, OpenAIIntentParser


class _UnusedModel:
    def parse(self, prompt: str) -> AgentIntent:
        raise ModelUnavailable("A model is required for a new prompt")


async def _run(args) -> dict:
    record_path = Path(args.data_root) / "harness" / "last-run.json"
    async with StdioMCPPort(args.data_root, allowed_roots=args.allow_root) as mcp:
        model = (_UnusedModel() if not args.prompt else
                 OpenAIIntentParser(
                     os.environ.get("OPENAI_API_KEY", ""), model=args.model,
                     ledger_path=Path(args.data_root) / "harness" / "cost-ledger.json"))
        agent = (ReferenceAgent.restore(mcp, model, record_path)
                 if record_path.is_file() and (args.resume or args.submit_kind)
                 else ReferenceAgent(mcp, model, record_path=record_path))
        if args.resume:
            result = await agent.resume(args.resume if args.resume != "last" else None)
        elif args.submit_kind:
            result = await agent.submit_plan(args.submit_kind)
        else:
            baseline_id = await mcp.upload_file(args.baseline_file) if args.baseline_file else None
            result = await agent.run(args.prompt, auto_submit=args.auto_submit,
                                     baseline_override=baseline_id)
        return {
            "status": result.status, "message": result.message,
            "plan_hash": result.plan_hash, "job_id": result.job_id,
            "artifact_ids": list(result.artifact_ids),
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="openepw-agent", description="Local reference agent over stdio MCP")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--allow-root", action="append", default=[])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prompt")
    action.add_argument("--resume", nargs="?", const="last", metavar="JOB_ID")
    action.add_argument("--submit-kind", choices=["weather", "future"])
    parser.add_argument("--auto-submit", action="store_true")
    parser.add_argument("--baseline-file")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(asyncio.run(_run(args)), indent=2))
        return 0
    except (ModelUnavailable, MCPToolFailure) as exc:
        code = exc.code if isinstance(exc, MCPToolFailure) else "MODEL_UNAVAILABLE"
        print(json.dumps({"code": code, "message": str(exc)}))
        return 2
