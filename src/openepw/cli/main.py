import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from ..availability import AvailabilityQuery
from ..availability.package import PackageError, export_package, load_package
from ..availability.stage1 import import_stage1
from ..availability.store import CatalogImportError
from ..config import RuntimeConfig
from ..epw import read_epw
from ..models import FutureRequest, OpenEPWError, WeatherPlan, WeatherRequest
from ..qc import validate
from ..service import WeatherService
from ..visualization import VisualizationRequest


def _security_arguments(parser, default: str) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--security-profile", choices=["local", "hosted"],
                       help=f"Committed security profile (default: {default})")
    group.add_argument("--security-file", type=Path,
                       help="A security YAML file; it may extend a profile (see config/security)")


def _security_policy(args, default: str, *, remote: bool = False):
    """Load the chosen security profile and say which one runs (and whether it is weakened)."""
    from ..agent.policy_config import describe, load_policy, weakened

    policy = load_policy(args.security_profile, file=args.security_file, default=default)
    print(describe(policy))
    notes = weakened(policy)
    if remote and notes:
        print("WARNING: serving remotely with a weakened security profile: " + "; ".join(notes) + ".")
        logging.getLogger("openepw.security").warning("Remote serve with a weakened profile: %s",
                                                      "; ".join(notes))
    return policy


def _default_eval_run(argv: list[str]) -> list[str]:
    """`openepw [global options] eval [options]` means `eval run`."""
    index = 0
    while index < len(argv) and argv[index].startswith("-"):
        option = argv[index]
        # argparse also accepts unambiguous prefixes such as --data for --data-root
        takes_value = "=" not in option and len(option) > 2 and any(
            name.startswith(option) for name in ("--env-file", "--data-root"))
        index += 2 if takes_value else 1
    if index < len(argv) and argv[index] == "eval":
        following = argv[index + 1] if index + 1 < len(argv) else None
        if following not in ("run", "compare", "lint", "catalog", "mutate", "labels", "-h", "--help"):
            argv.insert(index + 1, "run")
    return argv


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="openepw", description="Transparent weather retrieval and future climate EPWs"
    )
    parser.add_argument("--version", action="version", version="openepw 0.1.0")
    parser.add_argument("--env-file", help="Explicit ignored dotenv file (never persisted)")
    parser.add_argument("--data-root")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("geocode", "discover", "plan", "fetch", "execute", "future",
                    "future-plan", "register-baseline", "inspect", "availability",
                    "export", "visualize", "data-describe", "view-page"):
        cmd = sub.add_parser(command)
        cmd.add_argument(
            "input", help="Location text, request/plan JSON path, or EPW/job ID"
        )
        cmd.add_argument("--output", help="Write compact JSON result to this path")
        if command == "view-page":
            cmd.add_argument("--offset", type=int, default=0)
            cmd.add_argument("--limit", type=int, default=100)
    sub.add_parser("visualization-capabilities")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    _security_arguments(serve, "local on localhost, hosted otherwise")
    mcp = sub.add_parser("mcp")
    mcp.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    mcp.add_argument("--allow-root", action="append", default=[],
                     help="Allow MCP baseline path registration beneath this local directory")
    chat = sub.add_parser("chat", help="Weather chat over the local MCP server (agent or guided mode)")
    chat.add_argument("--session", help="Resume a saved chat session by ID")
    chat.add_argument("--mode", choices=["agent", "guided"],
                      help="Default: agent when OPENAI_API_KEY is set, otherwise guided")
    chat.add_argument("--model", default=None, help="OpenAI model id for agent mode")
    chat.add_argument("--max-cost", type=float, default=5.0,
                      help="Budget stop in USD for the local model usage ledger (default 5)")
    chat.add_argument("--reopen", action="store_true",
                      help="Reopen an ended session (only when the profile allows it)")
    _security_arguments(chat, "local")
    evals = sub.add_parser("eval", help="Run agent chat eval tasks, compare runs, lint and catalogue tasks")
    eval_sub = evals.add_subparsers(dest="eval_command", required=True)
    run = eval_sub.add_parser("run", help="Run tasks; write trial records, a summary and an HTML report")
    run.add_argument("--mode", choices=["guided", "agent"], default="guided")
    run.add_argument("--scripted", action="store_true",
                     help="Agent mode with each task's scripted model (offline, no key)")
    run.add_argument("--live", action="store_true",
                     help="Agent mode with the real OpenAI model (costs money; capped by --max-cost)")
    run.add_argument("--task", action="append", help="Task id, e.g. S1 (repeatable)")
    run.add_argument("--trials", type=int, default=None,
                     help="Trials per task (default: 1 offline; live 3, or 5 for safety tasks)")
    run.add_argument("--model", default=None, help="OpenAI model id for live agent runs")
    run.add_argument("--max-cost", type=float, default=1.0, help="Budget stop in USD for this eval run (default 1)")
    run.add_argument("--live-providers", action="store_true",
                     help="Use the real geocoder and providers instead of offline stubs")
    run.add_argument("--tasks", type=Path, help="A task YAML file or folder (default: the packaged tasks)")
    run.add_argument("--output-dir", type=Path, help="Results folder (default: <data root>/evals/<run id>)")
    run.add_argument("--baseline", type=Path,
                     help="Run folder or summary.json to compare with (default: the latest similar run)")
    _security_arguments(run, "local")
    eval_compare = eval_sub.add_parser("compare", help="Compare two runs (folders or summary.json files)")
    eval_compare.add_argument("baseline", type=Path)
    eval_compare.add_argument("current", type=Path)
    eval_lint = eval_sub.add_parser("lint", help="Check tasks for missing purpose, coverage, scripts and dead checks")
    eval_lint.add_argument("--tasks", type=Path)
    eval_catalog = eval_sub.add_parser("catalog", help="Write a Markdown and HTML catalogue of the tasks")
    eval_catalog.add_argument("--tasks", type=Path)
    eval_catalog.add_argument("--output-dir", type=Path, help="Default: <data root>/evals/catalog")
    eval_catalog.add_argument("--results", type=Path, help="A run folder whose pass rates to show")
    eval_labels = eval_sub.add_parser("labels", help="Write a blind labelling pack for judge calibration")
    eval_labels.add_argument("--run", action="append", required=True,
                             help="SOURCE=FOLDER of a run whose trials to draw from (repeatable)")
    eval_labels.add_argument("--count", action="append", required=True,
                             help="DIMENSION=N: decline, grounding or helpfulness (repeatable)")
    eval_labels.add_argument("--output-dir", type=Path, required=True)
    eval_labels.add_argument("--tasks", type=Path, help="Extra task files (e.g. probes) for coverage lookup")
    eval_labels.add_argument("--seed", type=int, default=7)
    eval_mutate = eval_sub.add_parser("mutate", help="Disable each guard in turn and check the tasks catch it")
    eval_mutate.add_argument("--tasks", type=Path)
    eval_mutate.add_argument("--mutation", action="append", help="Only this mutation (repeatable)")
    catalog = sub.add_parser("catalog")
    catalog_sub = catalog.add_subparsers(dest="catalog_command", required=True)
    catalog_sub.add_parser("status")
    catalog_import = catalog_sub.add_parser("import")
    source = catalog_import.add_mutually_exclusive_group(required=True)
    source.add_argument("--from", dest="snapshot_root", type=Path, help="Stage 1 research snapshot folder")
    source.add_argument("--from-package", type=Path, help="datapackage.json of a published catalog package")
    catalog_export = catalog_sub.add_parser("export", help="write the active catalog as a CSV data package")
    catalog_export.add_argument("--out", type=Path, required=True)
    catalog_export.add_argument("--name", default="weather-availability-catalog")
    catalog_export.add_argument("--package-version", required=True)
    catalog_export.add_argument("--metadata", type=Path, help="JSON merged into datapackage.json (title, licenses...)")
    args = parser.parse_args(_default_eval_run(list(sys.argv[1:] if argv is None else argv)))
    try:
        config = RuntimeConfig.load(
            env_file=args.env_file, **({"data_root": args.data_root} if args.data_root else {})
        )
        service = WeatherService(config)
        if args.command == "serve":
            import uvicorn

            from ..agent.policy_config import profile_for_serve
            from ..api.app import create_app

            remote = args.host not in ("127.0.0.1", "localhost", "::1")
            security = _security_policy(args, profile_for_serve(args.host), remote=remote)
            uvicorn.run(
                create_app(service, remote=remote, env_file=args.env_file or ".env",
                           security_policy=security),
                host=args.host,
                port=args.port,
                # One process: sessions are in SQLite and jobs run inside it. Explicit, because
                # uvicorn otherwise takes WEB_CONCURRENCY (Render sets 2 on larger instances),
                # and more than one worker with an app object makes uvicorn exit (status 3).
                workers=1,
            )
            return 0
        if args.command == "mcp":
            from ..mcp.server import create_server

            server = create_server(service, allowed_roots=args.allow_root)
            try:
                server.run(transport=args.transport)
            finally:
                server.openepw_runner.close()  # type: ignore[attr-defined]
            return 0
        if args.command == "eval":
            from ..agent.cli import prepare_console
            from ..agent.evals import command as evals_command

            prepare_console()
            evals_dir = config.data_root / "evals"
            if args.eval_command == "compare":
                return evals_command.main_compare(args.baseline, args.current)
            if args.eval_command == "lint":
                return evals_command.main_lint(tasks_path=args.tasks)
            if args.eval_command == "catalog":
                return evals_command.main_catalog(tasks_path=args.tasks, output_dir=args.output_dir or
                                                  evals_dir / "catalog", results=args.results)
            if args.eval_command == "labels":
                return evals_command.main_labels(runs=args.run, counts=args.count, output_dir=args.output_dir,
                                                 tasks_path=args.tasks, seed=args.seed)
            if args.eval_command == "mutate":
                return asyncio.run(evals_command.main_mutate(tasks_path=args.tasks, mutation_names=args.mutation))
            return asyncio.run(evals_command.main_run(
                mode=args.mode, scripted=args.scripted, live=args.live, task_ids=args.task, trials=args.trials,
                model=args.model, max_cost=args.max_cost, live_providers=args.live_providers,
                tasks_path=args.tasks, evals_dir=evals_dir, output_dir=args.output_dir, baseline=args.baseline,
                env_file=args.env_file or ".env", security=_security_policy(args, "local")))
        if args.command == "chat":
            from ..agent.cli import (
                chat_model,
                chat_moderation,
                chat_tracer,
                main_chat,
                prepare_console,
            )

            prepare_console()
            security = _security_policy(args, "local")
            moderation, problem = chat_moderation(security, args.env_file or ".env")
            if problem:
                print(problem)
                return 2
            model, notice = chat_model(args.mode, model=args.model, max_cost=args.max_cost,
                                       data_root=config.data_root, env_file=args.env_file or ".env")
            if notice:
                print(notice)
            tracer, tracing_notice = chat_tracer(args.env_file or ".env")
            if tracing_notice:
                print(tracing_notice)
            try:
                return asyncio.run(main_chat(service, session_id=args.session, model=model, tracer=tracer,
                                             security=security, reopen=args.reopen, moderation=moderation))
            except KeyboardInterrupt:
                print("\nChat interrupted; the session and completed artifacts stay in the data root.")
                return 130
        if args.command == "geocode":
            result = service.geocode(args.input)
        elif args.command == "visualization-capabilities":
            result = service.visualization_capabilities()
        elif args.command == "data-describe":
            artifact_ids = json.loads(Path(args.input).read_text(encoding="utf-8"))
            result = service.describe_weather_data(artifact_ids)
        elif args.command == "visualize":
            request = VisualizationRequest.model_validate_json(
                Path(args.input).read_text(encoding="utf-8"))
            result = service.visualize_weather(request)
        elif args.command == "view-page":
            result = service.page_weather_data(args.input, args.offset, args.limit)
        elif args.command == "catalog":
            if args.catalog_command == "status":
                view = service.catalog_store.active()
                expected = {"openmeteo", "pvgis", "onebuilding", "noaa", "nsrdb",
                            "cds", "cmip6", "oedi"}
                found = {product.provider for product in view.bundle.products} if view else set()
                result = {
                    "loaded": view is not None,
                    "generation_id": view.snapshot.generation_id if view else None,
                    "available_sources": sorted(found),
                    "missing_sources": sorted(expected - found),
                    "stale_sources": view.snapshot.stale_sources if view else [],
                }
            elif args.catalog_command == "export":
                view = service.catalog_store.active()
                if view is None:
                    raise CatalogImportError("No active catalog to export")
                metadata = json.loads(args.metadata.read_text(encoding="utf-8")) if args.metadata else None
                descriptor = export_package(view.bundle, args.out, config.data_root / "footprints",
                                            name=args.name, version=args.package_version, metadata=metadata)
                result = {"datapackage": str(descriptor),
                          "sha256": hashlib.sha256(descriptor.read_bytes()).hexdigest(),
                          "bytes": sum(r["bytes"] for r in json.loads(descriptor.read_text(encoding="utf-8"))["resources"])}
            else:
                if args.from_package:
                    loaded = load_package(args.from_package)
                    bundle = loaded.bundle
                    for relative, content in loaded.footprints.items():
                        footprint = config.data_root / "footprints" / relative
                        footprint.parent.mkdir(parents=True, exist_ok=True)
                        footprint.write_bytes(content)
                else:
                    bundle = import_stage1(args.snapshot_root)
                staged = service.catalog_store.stage(bundle)
                active = service.catalog_store.activate(staged.generation_id)
                result = {
                    "loaded": True,
                    "generation_id": active.generation_id,
                    "source_count": len(bundle.evidence),
                    "product_count": len(bundle.products),
                    "site_count": len(bundle.sites),
                    "entry_count": len(bundle.entries),
                    "review_count": len(bundle.reviews),
                }
        elif args.command == "inspect":
            path = Path(args.input)
            if path.is_file():
                if path.suffix.lower() == ".epw":
                    data = read_epw(path)
                    result = {
                        "rows": len(data.data),
                        "location": data.location.model_dump(),
                        "calendar": data.calendar,
                        "qc": [i.model_dump() for i in validate(data)],
                    }
                else:
                    result = json.loads(path.read_text())
            else:
                from ..jobs.store import JobStore

                result = JobStore(config.data_root).get(args.input)
        elif args.command == "export":
            from ..jobs.worker import JobRunner

            runner = JobRunner(service)
            try:
                result = runner.export_compact(args.input)
            finally:
                runner.close()
        elif args.command == "register-baseline":
            result = service.register_baseline(args.input)
        else:
            if args.command == "execute":
                selected_plan = (
                    service.plan_store.get(args.input)
                    if re.fullmatch(r"[0-9a-f]{64}", args.input)
                    else WeatherPlan.model_validate_json(Path(args.input).read_text(encoding="utf-8"))
                )
                result = service.execute(selected_plan)
            else:
                raw = Path(args.input).read_text(encoding="utf-8")
                if args.command == "future":
                    result = service.execute(
                        service.plan_future(FutureRequest.model_validate_json(raw))
                    )
                elif args.command == "future-plan":
                    result = service.plan_future(FutureRequest.model_validate_json(raw))
                elif args.command == "availability":
                    result = service.assess_availability(
                        TypeAdapter(AvailabilityQuery).validate_json(raw))
                else:
                    request = WeatherRequest.model_validate_json(raw)
                    result = getattr(service, args.command)(request)
        value = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        rendered = json.dumps(value, indent=2, allow_nan=False)
        if getattr(args, "output", None):
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return (
            1
            if isinstance(value, dict)
            and any(i.get("severity") == "error" for i in value.get("issues", []))
            else 0
        )
    except (OpenEPWError, ValidationError, OSError, ValueError) as exc:
        error = (
            exc.issue.model_dump()
            if isinstance(exc, OpenEPWError)
            else {"code": "CATALOG_IMPORT_ERROR", "message": str(exc)}
            if isinstance(exc, (CatalogImportError, PackageError))
            else {
                "code": "INVALID_REQUEST",
                "message": "Invalid request, configuration or local input file",
            }
        )
        print(json.dumps(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
