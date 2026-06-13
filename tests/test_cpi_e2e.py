from __future__ import annotations

import json
import os
from pathlib import Path
import traceback
from typing import Any
from uuid import uuid4

import pytest


QUESTION = "What has happened to CPI inflation over the last five years?"

REQUIRED_ARTIFACTS = [
    "input.json",
    "plan.json",
    "fred_search.json",
    "selected_data.json",
    "data.json",
    "generated_code.py",
    "code_output.json",
    "analysis.json",
    "checkpoint_results.json",
    "draft.json",
    "checker.json",
    "final_answer.json",
    "alarms.json",
    "state.json",
]


def test_cpi_e2e_uses_live_fred_with_mock_worker_and_checker(tmp_path: Path) -> None:
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        pytest.fail(
            "FRED_API_KEY not configured.\n"
            "Milestone 17 requires live FRED integration.\n"
            "Set FRED_API_KEY and rerun."
        )

    try:
        from app.observability import load_run_view
        from harness.orchestrator import Orchestrator
        from harness.state import RunState, Stage
        from workers.mock_checker import MockChecker
        from workers.mock_worker import MockWorker
    except Exception as exc:
        pytest.fail(_diagnostic_message(tmp_path, "", setup_error=exc))

    run_id = f"cpi-e2e-{uuid4().hex[:8]}"
    runs_dir = tmp_path / "runs"
    state = RunState(
        run_id=run_id,
        question=QUESTION,
        current_stage=Stage.INPUT,
        retry_count=0,
    )

    try:
        final_state = Orchestrator(
            state,
            runs_dir=runs_dir,
            worker=MockWorker(),
            checker=MockChecker(),
        ).run()
    except Exception as exc:
        pytest.fail(_diagnostic_message(runs_dir, run_id, execution_error=exc))

    failures = _acceptance_failures(runs_dir, run_id, final_state)
    if failures:
        pytest.fail(_diagnostic_message(runs_dir, run_id, failures=failures))

    try:
        run_view = load_run_view(run_id, runs_dir=runs_dir)
    except Exception as exc:
        pytest.fail(_diagnostic_message(runs_dir, run_id, observability_error=exc))

    if not run_view.get("artifacts"):
        pytest.fail(
            _diagnostic_message(
                runs_dir,
                run_id,
                failures=["Observability returned no artifacts for the run."],
            )
        )


def _acceptance_failures(runs_dir: Path, run_id: str, final_state: Any) -> list[str]:
    run_dir = runs_dir / run_id
    failures: list[str] = []
    missing = [name for name in REQUIRED_ARTIFACTS if not (run_dir / name).exists()]
    if missing:
        failures.append(f"Missing artifact names: {', '.join(missing)}")

    current_stage = getattr(getattr(final_state, "current_stage", None), "value", None)
    if current_stage != "released":
        failures.append(f"Expected final stage released, got {current_stage!r}.")

    fred_search = _read_json(run_dir / "fred_search.json")
    queries = fred_search.get("queries", []) if isinstance(fred_search, dict) else []
    if not queries:
        failures.append("fred_search.json did not record any FRED search queries.")
    elif not any(query.get("results") for query in queries if isinstance(query, dict)):
        failures.append("FRED search recorded no results.")

    selected_data = _read_json(run_dir / "selected_data.json")
    selected_series = selected_data.get("selected_series", []) if isinstance(selected_data, dict) else []
    if not any(series.get("series_id") == "CPIAUCSL" for series in selected_series if isinstance(series, dict)):
        failures.append("Selected series did not include CPIAUCSL.")

    data = _read_json(run_dir / "data.json")
    observations = data.get("observations", {}) if isinstance(data, dict) else {}
    cpi_observations = observations.get("CPIAUCSL", []) if isinstance(observations, dict) else []
    if len(cpi_observations) < 48:
        failures.append(
            f"Expected at least 48 CPI observations from live FRED, got {len(cpi_observations)}."
        )

    analysis = _read_json(run_dir / "analysis.json")
    metrics = analysis.get("metrics", []) if isinstance(analysis, dict) else []
    metric_names = {
        metric.get("name")
        for metric in metrics
        if isinstance(metric, dict) and isinstance(metric.get("name"), str)
    }
    expected_metrics = {
        "cpi_five_year_change_percent",
        "latest_yoy_inflation_percent",
    }
    missing_metrics = sorted(expected_metrics - metric_names)
    if missing_metrics:
        failures.append(f"Analysis missing metrics: {', '.join(missing_metrics)}")

    charts = analysis.get("charts", []) if isinstance(analysis, dict) else []
    if not charts:
        failures.append("Analysis did not include a chart descriptor.")

    checkpoints = _read_json(run_dir / "checkpoint_results.json")
    failed_checkpoints = [
        checkpoint
        for checkpoint in checkpoints.get("checks", [])
        if isinstance(checkpoint, dict) and not checkpoint.get("passed")
    ] if isinstance(checkpoints, dict) else []
    if failed_checkpoints:
        names = ", ".join(str(item.get("name")) for item in failed_checkpoints)
        failures.append(f"Checkpoint failure: {names}")

    draft = _read_json(run_dir / "draft.json")
    answer = draft.get("answer", "") if isinstance(draft, dict) else ""
    referenced_metrics = draft.get("referenced_metrics", []) if isinstance(draft, dict) else []
    if "CPI" not in answer or not referenced_metrics:
        failures.append("Draft answer was not grounded in CPI metrics.")

    checker = _read_json(run_dir / "checker.json")
    if isinstance(checker, dict) and checker.get("passed") is not True:
        failures.append(f"Checker did not pass: {checker}")

    final_answer = _read_json(run_dir / "final_answer.json")
    if not isinstance(final_answer, dict) or not final_answer.get("answer"):
        failures.append("final_answer.json did not contain a released answer.")

    return failures


def _diagnostic_message(
    runs_dir: Path,
    run_id: str,
    *,
    setup_error: BaseException | None = None,
    execution_error: BaseException | None = None,
    observability_error: BaseException | None = None,
    failures: list[str] | None = None,
) -> str:
    run_dir = runs_dir / run_id if run_id else runs_dir
    state = _read_json(run_dir / "state.json")
    alarms = _read_json(run_dir / "alarms.json")
    selected_data = _read_json(run_dir / "selected_data.json")
    fred_search = _read_json(run_dir / "fred_search.json")
    code_output = _read_json(run_dir / "code_output.json")
    checkpoints = _read_json(run_dir / "checkpoint_results.json")

    artifact_paths = []
    if run_dir.exists():
        artifact_paths = sorted(str(path) for path in run_dir.iterdir() if path.is_file())
    missing_artifacts = [
        name for name in REQUIRED_ARTIFACTS if not (run_dir / name).exists()
    ]
    latest_alarm = None
    if isinstance(alarms, list) and alarms:
        latest_alarm = alarms[-1]

    checkpoint_failure = None
    if isinstance(checkpoints, dict):
        checkpoint_failure = [
            item
            for item in checkpoints.get("checks", [])
            if isinstance(item, dict) and not item.get("passed")
        ]

    first_query = ""
    if isinstance(fred_search, dict) and fred_search.get("queries"):
        first = fred_search["queries"][0]
        if isinstance(first, dict):
            first_query = str(first.get("query", ""))

    error = setup_error or execution_error or observability_error
    formatted_traceback = (
        "".join(traceback.format_exception(type(error), error, error.__traceback__))
        if error is not None
        else ""
    )

    return "\n".join(
        [
            "CPI E2E failed.",
            f"Current Stage: {_stage_from_state(state)}",
            f"Run ID: {run_id or '<not created>'}",
            f"Artifact Paths Written: {artifact_paths}",
            f"Latest Alarm: {_json_string(latest_alarm)}",
            "Guardrail Failure: <none recorded>",
            f"Checkpoint Failure: {_json_string(checkpoint_failure)}",
            f"Selected Series: {_json_string(selected_data)}",
            f"FRED Search Query: {first_query}",
            f"Generated Code Path: {run_dir / 'generated_code.py'}",
            f"stdout:\n{_code_output_text(code_output, 'stdout')}",
            f"stderr:\n{_code_output_text(code_output, 'stderr')}",
            f"Traceback:\n{formatted_traceback}",
            f"Missing Artifact Names: {missing_artifacts}",
            f"Failures: {failures or []}",
        ]
    )


def _stage_from_state(state: Any) -> str:
    if isinstance(state, dict):
        return str(state.get("current_stage", "<unknown>"))
    return "<unknown>"


def _code_output_text(code_output: Any, key: str) -> str:
    if isinstance(code_output, dict):
        return str(code_output.get(key, ""))
    return ""


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _json_string(value: Any) -> str:
    try:
        return json.dumps(value, indent=2, sort_keys=True)
    except TypeError:
        return repr(value)
