"""Load run artifacts for presentation and observability views."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


LoadMode = Literal["fixture", "runs"]

DEFAULT_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"

ARTIFACT_FILES = {
    "input": "input.json",
    "timeline": "timeline.json",
    "guardrails": "guardrails.json",
    "checkpoints": "checkpoints.json",
    "alarms": "alarms.json",
    "planner": "planner.json",
    "search": "search.json",
    "data_selection": "data_selection.json",
    "code": "code.json",
    "analysis": "analysis.json",
    "draft": "draft.json",
    "checker": "checker.json",
}


@dataclass(frozen=True)
class RunArtifacts:
    """Normalized artifact bundle consumed by the UI."""

    run_id: str
    source: str
    root_path: Path
    input: dict[str, Any]
    timeline: list[dict[str, Any]]
    guardrails: list[dict[str, Any]]
    checkpoints: list[dict[str, Any]]
    alarms: list[dict[str, Any]]
    planner: dict[str, Any]
    search: dict[str, Any]
    data_selection: dict[str, Any]
    code: dict[str, Any]
    analysis: dict[str, Any]
    draft: dict[str, Any]
    checker: dict[str, Any]
    raw: dict[str, Any]


def load_run_artifacts(
    run_id: str,
    mode: LoadMode = "fixture",
    fixture_root: str | Path = DEFAULT_FIXTURE_ROOT,
    runs_dir: str | Path = "runs",
) -> RunArtifacts:
    """Load one run from fixture artifacts or persisted live runs."""

    if mode == "runs":
        return _load_live_run(run_id, Path(runs_dir))
    if mode != "fixture":
        raise ValueError(f"Unsupported observability load mode: {mode!r}")

    run_dir = Path(fixture_root) / run_id
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Fixture run not found: {run_id}")

    raw = {
        artifact_name: _read_json(run_dir / filename)
        for artifact_name, filename in ARTIFACT_FILES.items()
    }

    return RunArtifacts(
        run_id=run_id,
        source="fixture",
        root_path=run_dir,
        input=dict(raw["input"]),
        timeline=_list_of_dicts(raw["timeline"], "timeline"),
        guardrails=_list_of_dicts(raw["guardrails"], "guardrails"),
        checkpoints=_list_of_dicts(raw["checkpoints"], "checkpoints"),
        alarms=_list_of_dicts(raw["alarms"], "alarms"),
        planner=dict(raw["planner"]),
        search=dict(raw["search"]),
        data_selection=dict(raw["data_selection"]),
        code=dict(raw["code"]),
        analysis=dict(raw["analysis"]),
        draft=dict(raw["draft"]),
        checker=dict(raw["checker"]),
        raw=raw,
    )


def _load_live_run(run_id: str, runs_dir: Path) -> RunArtifacts:
    run_dir = runs_dir / run_id
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    def read(name: str, default: Any) -> Any:
        path = run_dir / name
        if not path.is_file():
            return default
        if path.suffix == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        return path.read_text(encoding="utf-8")

    checkpoints_payload = read("checkpoint_results.json", {"checks": []})
    if isinstance(checkpoints_payload, dict):
        checkpoints = list(checkpoints_payload.get("checks") or [])
    elif isinstance(checkpoints_payload, list):
        checkpoints = checkpoints_payload
    else:
        checkpoints = []

    generated_code = read("generated_code.py", "")
    code = generated_code if isinstance(generated_code, dict) else {"code": generated_code}
    draft = read("draft.json", {}) or read("final_answer.json", {})

    raw = {
        "input": read("input.json", {}),
        "timeline": read("timeline.json", []),
        "guardrails": read("guardrails.json", []),
        "checkpoints": checkpoints,
        "alarms": read("alarms.json", []),
        "planner": read("plan.json", {}),
        "search": read("fred_search.json", {}),
        "data_selection": read("selected_data.json", {}),
        "code": code,
        "analysis": read("analysis.json", {}),
        "chart_brief": read("chart_brief.json", {}),
        "draft": draft,
        "checker": read("checker.json", {}),
        "state": read("state.json", {}),
        "final_answer": read("final_answer.json", {}),
    }

    return RunArtifacts(
        run_id=run_id,
        source="runs",
        root_path=run_dir,
        input=_as_dict(raw["input"]),
        timeline=_list_of_dicts(raw["timeline"], "timeline", strict=False),
        guardrails=_list_of_dicts(raw["guardrails"], "guardrails", strict=False),
        checkpoints=_list_of_dicts(raw["checkpoints"], "checkpoints", strict=False),
        alarms=_list_of_dicts(raw["alarms"], "alarms", strict=False),
        planner=_as_dict(raw["planner"]),
        search=_as_dict(raw["search"]),
        data_selection=_as_dict(raw["data_selection"]),
        code=_as_dict(raw["code"]),
        analysis=_as_dict(raw["analysis"]),
        draft=_as_dict(raw["draft"]),
        checker=_as_dict(raw["checker"]),
        raw=raw,
    )


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(f"Missing observability artifact: {path.name}")
    return json.loads(path.read_text())


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_of_dicts(value: Any, artifact_name: str, *, strict: bool = True) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        if strict:
            raise ValueError(f"{artifact_name} must be a list")
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
