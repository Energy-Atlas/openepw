import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from ..availability import AvailabilityQuery
from ..availability.stage1 import import_stage1
from ..availability.store import CatalogImportError
from ..config import RuntimeConfig
from ..epw import read_epw
from ..models import FutureRequest, OpenEPWError, WeatherPlan, WeatherRequest
from ..qc import validate
from ..service import WeatherService


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="openepw", description="Transparent weather retrieval and future climate EPWs"
    )
    parser.add_argument("--version", action="version", version="openepw 0.1.0")
    parser.add_argument("--env-file", help="Explicit ignored dotenv file (never persisted)")
    parser.add_argument("--data-root")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("geocode", "discover", "plan", "fetch", "execute", "future",
                    "inspect", "availability", "export"):
        cmd = sub.add_parser(command)
        cmd.add_argument(
            "input", help="Location text, request/plan JSON path, or EPW/job ID"
        )
        cmd.add_argument("--output", help="Write compact JSON result to this path")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    mcp = sub.add_parser("mcp")
    mcp.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    catalog = sub.add_parser("catalog")
    catalog_sub = catalog.add_subparsers(dest="catalog_command", required=True)
    catalog_sub.add_parser("status")
    catalog_import = catalog_sub.add_parser("import")
    catalog_import.add_argument("--from", dest="snapshot_root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        config = RuntimeConfig.load(
            env_file=args.env_file, **({"data_root": args.data_root} if args.data_root else {})
        )
        service = WeatherService(config)
        if args.command == "serve":
            import uvicorn

            from ..api.app import create_app

            uvicorn.run(
                create_app(service, remote=args.host not in ("127.0.0.1", "localhost", "::1")),
                host=args.host,
                port=args.port,
            )
            return 0
        if args.command == "mcp":
            from ..mcp.server import create_server

            create_server(service).run(transport=args.transport)
            return 0
        if args.command == "geocode":
            result = service.geocode(args.input)
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
        else:
            raw = Path(args.input).read_text(encoding="utf-8")
            if args.command == "execute":
                result = service.execute(WeatherPlan.model_validate_json(raw))
            elif args.command == "future":
                result = service.execute(
                    service.plan_future(FutureRequest.model_validate_json(raw))
                )
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
            if isinstance(exc, CatalogImportError)
            else {
                "code": "INVALID_REQUEST",
                "message": "Invalid request, configuration or local input file",
            }
        )
        print(json.dumps(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
