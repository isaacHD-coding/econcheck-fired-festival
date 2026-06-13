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
) -> RunArtifacts:
    """Load one run from fixture artifacts.

    The ``runs`` mode is intentionally a seam only. Runtime persistence is owned
    by another thread, so this branch does not read or write real run output.
    """

    if mode == "runs":
        raise NotImplementedError("Real run loading is a future integration seam.")
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


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(f"Missing observability artifact: {path.name}")
    return json.loads(path.read_text())


def _list_of_dicts(value: Any, artifact_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{artifact_name} must be a list")
    return [dict(item) for item in value]
