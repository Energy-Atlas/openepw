"""`openepw eval`: run the packaged scenarios in guided mode, with scripted models, or live."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..model_port import DEFAULT_MODEL, ModelPort, OpenAIModel, load_openai_key
from .runner import RunResult, load_scenarios, report_json, run_evals, scripted_model


async def main_eval(*, mode: str = "guided", scripted: bool = False, scenario_ids: list[str] | None = None,
                    repeats: int = 1, model: str | None = None, max_cost: float = 1.0,
                    live_providers: bool = False, scenarios_file: Path | None = None,
                    output: Path | None = None, env_file: str | Path | None = ".env",
                    write: Callable[[str], Any] = print) -> int:
    """Returns 0 when every run passed, 1 when any failed, 2 when the eval could not start."""
    scenarios = load_scenarios(scenarios_file)
    if scenario_ids:
        wanted = {item.upper() for item in scenario_ids}
        scenarios = [scenario for scenario in scenarios if scenario["id"].upper() in wanted]
    if not scenarios:
        write("No scenarios matched.")
        return 2
    factory: Callable[[dict[str, Any]], ModelPort | None] | None = None
    live_model: OpenAIModel | None = None
    if mode == "agent" and scripted:
        def factory(scenario: dict[str, Any]) -> ModelPort | None:
            return scripted_model(scenario) if "script" in scenario else None
    elif mode == "agent":
        key = load_openai_key(env_file)
        if not key:
            write("Live agent evals need OPENAI_API_KEY (environment or .env); use --scripted to run offline.")
            return 2
        # One in-memory ledger for this eval run; it stops at --max-cost.
        live_model = OpenAIModel(key, model=model or DEFAULT_MODEL, max_cost_usd=max_cost)
        shared = live_model

        def factory(scenario: dict[str, Any]) -> ModelPort | None:
            return shared

    def show(result: RunResult) -> None:
        status = "pass" if result.passed else "FAIL " + ",".join(result.failures)
        write(f"{result.scenario:4} {result.mode:6} {status:40} steps={result.model_steps:<2} "
              f"{result.seconds:6.1f}s ${result.cost_usd:.4f}")

    label = "scripted" if scripted else (live_model.name if live_model else "none")
    write(f"openepw eval · mode {mode} · model {label} · repeats {repeats} · "
          f"providers {'live' if live_providers else 'stubbed'}")
    reports = await run_evals(scenarios, mode=mode, model_factory=factory, repeats=repeats,
                              live_providers=live_providers, on_result=show)
    summary = report_json(reports, mode=mode, model=label, repeats=repeats,
                          providers="live" if live_providers else "stubbed")
    write(f"{summary['passed']}/{summary['runs']} runs passed; estimated model cost ${summary['cost_usd']:.4f}")
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0 if summary["runs"] and summary["passed"] == summary["runs"] else 1
