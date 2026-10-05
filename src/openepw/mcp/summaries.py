"""Short text summaries of MCP tool results for model context.

Full data stays in ``structuredContent`` for renderers; the text names what a model needs
to continue (identifiers, counts, statuses) and never repeats data rows.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

LIMIT = 1500
ROWS = 10


def _clip(text: str) -> str:
    return text if len(text) <= LIMIT else text[:LIMIT - 1] + "…"


def _point(row: dict) -> str:
    name = row.get("name") or row.get("input") or "point"
    lat, lon = row.get("lat"), row.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return f"{name} ({lat:.4f}, {lon:.4f})"
    return str(name)


def _codes(items: list[dict]) -> str:
    codes = sorted({item["code"] for item in items if item.get("code")})
    return ", ".join(codes) if codes else "none"


def _geocode(data: dict) -> str:
    candidates = data.get("candidates", [])
    lines = [f"{len(candidates)} location candidates for '{data.get('query', '')}'"
             + ("; ambiguous, the person must choose one." if len(candidates) > 1 else ".")]
    lines += [f"{index}. {_point(item)} id={item.get('id')}"
              for index, item in enumerate(candidates[:ROWS], start=1)]
    return "\n".join(lines)


def _interpret(data: dict) -> str:
    kind = data.get("kind")
    if data.get("questions"):
        prompts = "; ".join(str(question.get("prompt", "")) for question in data["questions"])
        return (f"Place text is {kind}; ask the person: {prompts}. "
                "Pass the returned draft back with their reply.")
    if kind == "list":
        items = data.get("items", [])
        return f"Place text is a list of {len(items)} places: " + "; ".join(map(str, items[:ROWS]))
    if kind == "coordinates":
        return f"Place text is {len(data.get('points', []))} coordinate points."
    if kind == "invalid":
        return "Place text is invalid: " + str((data.get("issue") or {}).get("message", ""))
    return f"Place text is {kind}."


def _preview(data: dict) -> str:
    rows = data.get("rows", [])
    ambiguous = sum(bool(row.get("ambiguous")) for row in rows)
    unresolved = sum(row.get("status") != "resolved" for row in rows)
    lines = [f"Previewed {data.get('resolved', 0)} of {data.get('count', len(rows))} places "
             f"(digest {str(data.get('digest', ''))[:12]}); {ambiguous} ambiguous, {unresolved} unresolved."]
    lines += [f"{row.get('index')}. {_point(row)} [{row.get('status')}]" for row in rows[:ROWS]]
    if len(rows) > ROWS:
        lines.append(f"... {len(rows) - ROWS} more rows in the structured data.")
    return "\n".join(lines)


def _review(data: dict) -> str:
    points = "; ".join(_point(point) for point in data.get("points", [])[:ROWS])
    return (f"{data.get('point_count')} point(s): {points}. {data.get('standard_time')} "
            f"Location key {data.get('key')}. Ask the person to approve these locations before planning.")


def _offers(data: dict) -> str:
    options = data.get("options", [])
    years = (data.get("availability") or {}).get("years")
    lines = [f"{len(options)} product offers (catalog years {years}):"]
    lines += [f"- {option['id']}: {option['label']} · {option.get('available', 0)}/{option.get('sites', 0)} "
              f"listed, {option.get('unverified', 0)} unverified" for option in options[:2 * ROWS]]
    lines.append("Listed means eligible to try retrieval, not quality assured. The person chooses.")
    return "\n".join(lines)


def _assess(data: dict) -> str:
    options = data.get("options", [])
    lines = [f"{len(options)} catalog options; issue codes {_codes(data.get('issues', []))}"]
    for option in options[:ROWS]:
        product, eligibility = option.get("product") or {}, option.get("eligibility") or {}
        lines.append(f"- {product.get('provider')}/{product.get('dataset')} at location "
                     f"{option.get('occurrence_index')}: {eligibility.get('status')}"
                     + (", stale evidence" if eligibility.get("stale") else ""))
    return "\n".join(lines)


def _discover(data: dict) -> str:
    candidates = data.get("candidates", [])
    names = ", ".join(f"{(item.get('source') or {}).get('provider')}/{(item.get('source') or {}).get('dataset')}"
                      for item in candidates[:ROWS])
    return f"{len(candidates)} source candidates: {names}."


def _plan(data: dict) -> str:
    text = (f"plan_hash {data.get('plan_hash')} ({data.get('kind')}): {data.get('output_count')} outputs, "
            f"{data.get('batch_row_count')} batch rows, {data.get('estimated_calls')} estimated source calls, "
            f"{len(data.get('warnings', []))} warnings, issue codes {_codes(data.get('issues', []))}.")
    if data.get("truncated"):
        text += " Rows are truncated; page them with plan_inspect."
    return text


def _job(data: dict) -> str:
    artifacts = data.get("artifacts") or {}
    text = (f"job {data.get('id')} {data.get('state')}: {data.get('completed', 0)}/{data.get('total', 0)} "
            f"completed, {data.get('failed', 0)} failed; {artifacts.get('weather_count', 0)} weather artifacts; "
            f"{data.get('error_count', 0)} errors.")
    if data.get("cancellation_requested"):
        text += " Cancellation requested."
    return text


def _artifact(data: dict) -> str:
    text = (f"artifact {data.get('artifact_id')} role={data.get('role')} {data.get('bytes')} bytes "
            f"sha256={str(data.get('sha256', ''))[:12]}")
    if "simulation_ready" in data:
        text += f"; simulation_ready={data.get('simulation_ready')}"
    if data.get("qc_issue_codes"):
        text += f"; QC codes {', '.join(data['qc_issue_codes'])}"
    return text + "."


def _upload(data: dict) -> str:
    return (f"Registered EPW artifact {data.get('artifact_id')}: {data.get('rows')} rows; "
            f"input QC codes {_codes(data.get('input_qc', []))}.")


def _capabilities(data: dict) -> str:
    families = ", ".join(f"{item['family']} ({item['status']})" for item in data.get("families", []))
    return f"View families: {families}. Variables: {', '.join(data.get('variables', {}))}."


def _describe(data: dict) -> str:
    lines = []
    for source in data.get("sources", [])[:ROWS]:
        variables = ", ".join(f"{name} missing {entry.get('missing_hours')}h"
                              for name, entry in (source.get("variables") or {}).items())
        lines.append(f"{source.get('artifact_id')} {source.get('years')}: {variables}")
    return "\n".join(lines) or "No sources described."


def _view(data: dict) -> str:
    spec = (data.get("specs") or [{}])[0]
    request = data.get("request") or {}
    text = (f"view_id {data.get('view_id')}: {spec.get('family') or request.get('family')} of "
            f"{request.get('variable')}. {spec.get('summary', '')} {data.get('total_rows')} rows prepared; "
            "the renderer draws and pages them.")
    if data.get("warnings"):
        text += " Warnings: " + _codes(data["warnings"]) + "."
    return text


def _page(data: dict) -> str:
    return (f"view_id {data.get('view_id')}: {len(data.get('rows', []))} of {data.get('total_rows')} rows; "
            f"next_offset {data.get('next_offset')}.")


def _export(data: dict) -> str:
    return f"Compact ZIP artifact {data.get('artifact_id')}: {data.get('bytes')} bytes; {data.get('uri')}."


SUMMARIES: dict[str, Callable[[dict], str]] = {
    "weather_geocode": _geocode, "weather_places_interpret": _interpret,
    "weather_places_preview": _preview, "weather_place_set": _preview,
    "weather_locations_review": _review, "weather_product_offers": _offers,
    "weather_assess": _assess, "weather_discover": _discover,
    "weather_plan": _plan, "plan_inspect": _plan,
    "weather_submit": _job, "weather_fetch": _job, "job_inspect": _job, "job_cancel": _job,
    "job_retry_failed": _job, "artifact_inspect": _artifact,
    "epw_upload": _upload, "epw_register_path": _upload,
    "weather_visualization_capabilities": _capabilities, "weather_data_describe": _describe,
    "weather_visualize": _view, "weather_data_page": _page, "weather_export_compact": _export,
}


def _inspect(data: dict) -> str:
    return _artifact(data) if data.get("artifact_id") and "state" not in data else _job(data)


SUMMARIES["weather_inspect"] = _inspect

IDENTIFIER_KEYS = ("plan_hash", "id", "job_id", "artifact_id", "view_id", "digest", "key", "state",
                   "kind", "code")


def _stub(tool: str, data: Any) -> str:
    """Field names and identifiers only; never data values, so it is safe for any payload."""
    try:
        if not isinstance(data, dict):
            return f"{tool} result"
        text = f"{tool} result; fields: " + ", ".join(sorted(map(str, data)))
        pairs = [f"{key}={data[key]}" for key in IDENTIFIER_KEYS
                 if isinstance(data.get(key), (str, int, bool))]
        return _clip(text + ("; " + ", ".join(pairs) if pairs else ""))
    except Exception:
        return f"{tool} result"


def summarize(tool: str, data: Any) -> str:
    """A short text for model context; unknown tools or odd data fall back to a key-only stub."""
    function = SUMMARIES.get(tool)
    if function is not None and isinstance(data, dict):
        try:
            return _clip(function(data))
        except Exception as exc:
            logging.getLogger("openepw.mcp").warning(
                "summary failed for %s: %s", tool, type(exc).__name__)
    return _stub(tool, data)
