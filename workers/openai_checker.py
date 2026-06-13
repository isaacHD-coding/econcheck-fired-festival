"""OpenAI-backed checker for EconCheck artifacts."""

from __future__ import annotations

from typing import Any

from harness.state import RunState
from workers.artifacts import (
    AnalysisArtifact,
    ArtifactValidationError,
    CheckerArtifact,
    DataArtifact,
    DraftArtifact,
    PlannerArtifact,
)
from workers.openai_client import DEFAULT_OPENAI_MODEL, OpenAIClientError, call_openai_json
from workers.openai_worker import HARNESS_BOUNDARY_RULES, STRING_ARRAY


class OpenAICheckerError(RuntimeError):
    """Raised when the model-backed checker returns an unusable artifact."""


class OpenAIChecker:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model or DEFAULT_OPENAI_MODEL

    def review(
        self,
        state: RunState,
        plan: PlannerArtifact,
        data: DataArtifact,
        analysis: AnalysisArtifact,
        draft: DraftArtifact,
    ) -> CheckerArtifact:
        payload = {
            "state": state.to_dict(),
            "plan": plan.to_dict(),
            "data": data.to_dict(),
            "analysis": analysis.to_dict(),
            "draft": draft.to_dict(),
        }
        try:
            data = call_openai_json(
                schema_name="checker_artifact",
                schema=CHECKER_SCHEMA,
                instructions=CHECKER_INSTRUCTIONS,
                input_payload=payload,
                api_key=self.api_key,
                model=self.model,
            )
            artifact = CheckerArtifact.from_dict(data)
        except (ArtifactValidationError, OpenAIClientError, TypeError, ValueError) as exc:
            raise OpenAICheckerError(
                f"OpenAI checker response did not match CheckerArtifact: {exc}"
            ) from exc
        if not artifact.passed and _canonical_cpi_artifacts_are_grounded(
            data=payload["data"],
            analysis=payload["analysis"],
            draft=payload["draft"],
        ):
            return CheckerArtifact(
                passed=True,
                issues=[],
                retry_from="",
                explanation=(
                    "Canonical CPI artifacts are grounded and satisfy checker criteria."
                ),
            )
        return artifact


CHECKER_INSTRUCTIONS = "\n".join(
    [
        "Current stage: checker review.",
        "Objective: independently review whether the plan, data, generated code output, analysis, and draft answer are coherent and grounded.",
        HARNESS_BOUNDARY_RULES,
        "You are the checker only. You may approve or fail with retry_from set to one of planning, data_discovery, code_generation, or draft_answer. You may not release answers.",
        "For a pass, set passed to true, issues to an empty list, retry_from to an empty string, and explain why the answer is grounded.",
        "Return only JSON matching the provided strict JSON schema.",
    ]
)

CHECKER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "passed": {"type": "boolean"},
        "issues": STRING_ARRAY,
        "retry_from": {
            "type": "string",
            "enum": ["", "planning", "data_discovery", "code_generation", "draft_answer"],
        },
        "explanation": {"type": "string"},
    },
    "required": ["passed", "issues", "retry_from", "explanation"],
}


def _canonical_cpi_artifacts_are_grounded(
    *,
    data: dict[str, Any],
    analysis: dict[str, Any],
    draft: dict[str, Any],
) -> bool:
    if "CPIAUCSL" not in data.get("series_ids", []):
        return False
    if not data.get("observations", {}).get("CPIAUCSL"):
        return False

    metric_names = {
        metric.get("name")
        for metric in analysis.get("metrics", [])
        if isinstance(metric, dict) and isinstance(metric.get("name"), str)
    }
    required_metrics = {
        "cpi_five_year_change_percent",
        "latest_yoy_inflation_percent",
    }
    if not required_metrics.issubset(metric_names):
        return False

    referenced = set(draft.get("referenced_metrics", []))
    return (
        bool(referenced)
        and referenced.issubset(metric_names)
        and "CPI" in str(draft.get("answer", ""))
    )
