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


def test_real_openai_agent_e2e_uses_live_fred_and_openai(tmp_path: Path) -> None:
    missing_keys = [
        key for key in ["FRED_API_KEY", "OPENAI_API_KEY"] if not os.environ.get(key)
    ]
    if missing_keys:
        pytest.fail(
            "Required live E2E API keys not configured: "
            f"{', '.join(missing_keys)}.\n"
            "Set FRED_API_KEY and OPENAI_API_KEY and rerun."
        )

    try:
        from app.observability import load_run_view
        from harness.orchestrator import Orchestrator
        from harness.state import RunState, Stage
        from workers.openai_checker import OpenAIChecker
        from workers.openai_worker import OpenAIWorker
    except Exception as exc:
        pytest.fail(_diagnostic_message(tmp_path, "", setup_error=exc))

    run_id = f"real-agent-e2e-{uuid4().hex[:8]}"
    runs_dir = tmp_path / "runs"
    state = RunState(run_id, QUESTION, Stage.INPUT, 0)

    try:
        final_state = Orchestrator(
            state,
            runs_dir=runs_dir,
            worker=OpenAIWorker(),
            checker=OpenAIChecker(),
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
                failures=["Observability returned no artifacts for the real-agent run."],
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

    data = _read_json(run_dir / "data.json")
    observations = data.get("observations", {}) if isinstance(data, dict) else {}
    if not observations:
        failures.append("data.json did not include fetched FRED observations.")

    checker = _read_json(run_dir / "checker.json")
    if isinstance(checker, dict) and checker.get("passed") is not True:
        failures.append(f"Checker did not pass: {checker}")

    final_answer = _read_json(run_dir / "final_answer.json")
    if not isinstance(final_answer, dict) or not final_answer.get("answer"):
        failures.append("final_answer.json did not contain a released answer.")

    checkpoints = _read_json(run_dir / "checkpoint_results.json")
    failed_checkpoints = [
        checkpoint
        for checkpoint in checkpoints.get("checks", [])
        if isinstance(checkpoint, dict) and not checkpoint.get("passed")
    ] if isinstance(checkpoints, dict) else []
    if failed_checkpoints:
        failures.append(
            "Checkpoint failure: "
            + ", ".join(str(item.get("name")) for item in failed_checkpoints)
        )

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
    latest_alarm = alarms[-1] if isinstance(alarms, list) and alarms else None

    artifact_paths = []
    if run_dir.exists():
        artifact_paths = sorted(str(path) for path in run_dir.iterdir() if path.is_file())
    checkpoint_failure = []
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
    missing_artifacts = [
        name for name in REQUIRED_ARTIFACTS if not (run_dir / name).exists()
    ]

    return "\n".join(
        [
            "Real-agent E2E failed.",
            f"Run ID: {run_id or '<not created>'}",
            f"Stage: {_stage_from_state(state)}",
            f"Latest Alarm: {_json_string(latest_alarm)}",
            f"Selected Series: {_json_string(selected_data)}",
            f"FRED Query: {first_query}",
            f"Generated Code Path: {run_dir / 'generated_code.py'}",
            f"stdout:\n{_code_output_text(code_output, 'stdout')}",
            f"stderr:\n{_code_output_text(code_output, 'stderr')}",
            f"Traceback:\n{formatted_traceback}",
            f"Checkpoint Failures: {_json_string(checkpoint_failure)}",
            f"Missing Artifacts: {missing_artifacts}",
            f"Artifact Paths: {artifact_paths}",
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
