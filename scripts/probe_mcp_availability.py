"""Bounded MCP Stage 1 research; plan/analyze/report never access the network."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from mcp_research.analysis import analyze, report
from mcp_research.collector import Collector, Limits, Request
from mcp_research.sources import manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "collect", "analyze", "report"))
    parser.add_argument("--root", type=Path, default=Path(".local/mcp-availability"))
    parser.add_argument("--only", nargs="+")
    parser.add_argument("--manifest", type=Path, help="Explicit additional research requests")
    args = parser.parse_args(argv)
    requests = manifest()
    if args.manifest:
        for entry in json.loads(args.manifest.read_text(encoding="utf-8")):
            request = Request(**entry)
            if request.id in requests:
                parser.error("Additional manifest cannot replace built-in requests")
            requests[request.id] = request
    if args.only and any(key not in requests for key in args.only):
        parser.error("Unknown selected request")
    selected = [requests[key] for key in args.only] if args.only else list(requests.values())
    if args.command == "plan":
        print(
            json.dumps(
                {"limits": asdict(Limits()), "requests": [r.public() for r in selected]}, indent=2
            )
        )
    elif args.command == "collect":
        if not args.only:
            parser.error("collect requires explicit --only request identifiers")
        with Collector(args.root) as collector:
            for request in selected:
                result = collector.collect(request)
                print(
                    json.dumps(
                        {
                            "id": result["id"],
                            "outcome": result["outcome"],
                            "bytes_read": result["bytes_read"],
                        }
                    ),
                    flush=True,
                )
    elif args.command == "analyze":
        args.root.mkdir(parents=True, exist_ok=True)
        result = analyze(args.root)
        print(
            json.dumps(
                {
                    "eligibility": "unknown",
                    "inventories": list(result["inventories"]),
                    "errors": result["errors"],
                }
            )
        )
    else:
        args.root.mkdir(parents=True, exist_ok=True)
        result = report(args.root)
        print(
            json.dumps(
                {
                    "eligibility": "unknown",
                    "providers": len(result["providers"]),
                    "output": str(args.root / "report.md"),
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
