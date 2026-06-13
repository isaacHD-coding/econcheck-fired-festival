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
            return CheckerArtifact.from_dict(data)
        except (ArtifactValidationError, OpenAIClientError, TypeError, ValueError) as exc:
            raise OpenAICheckerError(
                f"OpenAI checker response did not match CheckerArtifact: {exc}"
            ) from exc


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
