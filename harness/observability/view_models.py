"""Pure helpers for rendering observability artifacts."""

from __future__ import annotations

from typing import Any

from harness.observability.loader import RunArtifacts


STAGE_ORDER = [
    ("input_guardrails", "Input Guardrails"),
    ("planning", "Planning"),
    ("data_discovery", "Data Discovery"),
    ("code_generation", "Code Generation"),
    ("draft_answer", "Draft Answer"),
    ("release", "Release"),
]

STAGE_ARTIFACTS = {
    "input_guardrails": "guardrails",
    "planning": "planner",
    "data_discovery": "data_selection",
    "code_generation": "code",
    "draft_answer": "analysis",
    "release": "draft",
}

STATUS_ICONS = {
    "complete": "✓",
    "active": "●",
    "warning": "!",
    "failed": "×",
    "pending": "○",
}


def progress_stages(run: RunArtifacts) -> list[dict[str, Any]]:
    timeline_by_id = {item.get("stage_id"): item for item in run.timeline}
    stages = []

    for stage_id, label in STAGE_ORDER:
        item = dict(timeline_by_id.get(stage_id, {}))
        status = str(item.get("status", "pending")).lower()
        stages.append(
            {
                "stage_id": stage_id,
                "label": item.get("label", label),
                "status": status,
                "icon": STATUS_ICONS.get(status, STATUS_ICONS["pending"]),
                "summary": item.get("summary", ""),
                "artifact_key": item.get("artifact_key", STAGE_ARTIFACTS[stage_id]),
            }
        )

    return stages


def artifact_for_stage(run: RunArtifacts, stage_id: str) -> Any:
    artifact_key = STAGE_ARTIFACTS.get(stage_id)
    if artifact_key is None:
        raise KeyError(f"Unknown timeline stage: {stage_id}")
    return getattr(run, artifact_key)


def planner_summary(planner: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_type": planner.get("question_type", ""),
        "economic_concepts": list(planner.get("economic_concepts", [])),
        "measurement_strategy": planner.get("measurement_strategy", ""),
        "information_requirements": list(planner.get("information_requirements", [])),
        "search_queries": list(planner.get("search_queries", [])),
        "required_outputs": list(planner.get("required_outputs", [])),
        "success_criteria": list(planner.get("success_criteria", [])),
    }


def analysis_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "metrics": list(analysis.get("metrics", [])),
        "claims": list(analysis.get("claims", [])),
        "charts": list(analysis.get("charts", [])),
        "warnings": list(analysis.get("warnings", [])),
        "tables": list(analysis.get("tables", [])),
        "method_notes": analysis.get("method_notes", ""),
    }


def answer_text(run: RunArtifacts) -> str:
    return str(run.draft.get("answer", ""))


def chart_specs(run: RunArtifacts) -> list[dict[str, Any]]:
    return list(run.analysis.get("charts", []))


def selected_series(run: RunArtifacts) -> list[dict[str, Any]]:
    return list(run.data_selection.get("selected_series", []))
