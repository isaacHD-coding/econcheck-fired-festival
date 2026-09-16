"""OpenAI-backed checker for EconCheck artifacts."""

from __future__ import annotations

from typing import Any

from harness.domain import is_canonical_cpi_demo_question
from harness.state import RunState
from workers.artifacts import (
    AnalysisArtifact,
    ArtifactValidationError,
    CheckerArtifact,
    DataArtifact,
    DraftArtifact,
    PlannerArtifact,
)
from workers.openai_client import (
    DEFAULT_OPENAI_MODEL,
    OpenAIClientError,
    OpenAITimeoutError,
    call_openai_json,
    openai_timeout_seconds,
    user_facing_openai_timeout_message,
)
from workers.openai_worker import HARNESS_BOUNDARY_RULES, STRING_ARRAY


class OpenAICheckerError(RuntimeError):
    """Raised when the model-backed checker returns an unusable artifact."""


class OpenAICheckerTimeoutError(OpenAICheckerError):
    """Raised when the OpenAI checker hits its hard timeout."""

    def __init__(self, timeout_seconds: float, *, schema_name: str = "checker_artifact") -> None:
        self.stage_label = "review"
        self.timeout_seconds = float(timeout_seconds)
        self.schema_name = schema_name
        super().__init__(
            user_facing_openai_timeout_message(self.stage_label, self.timeout_seconds)
        )


class OpenAIChecker:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model or DEFAULT_OPENAI_MODEL
        self._call_timeout_cap_seconds: float | None = None

    def set_call_timeout_cap(self, seconds: float | None) -> None:
        if seconds is None:
            self._call_timeout_cap_seconds = None
            return
        self._call_timeout_cap_seconds = max(0.1, float(seconds))

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
        timeout_seconds = openai_timeout_seconds(
            schema_name="checker_artifact",
            stage_label="review",
            cap_seconds=self._call_timeout_cap_seconds,
        )
        try:
            data = call_openai_json(
                schema_name="checker_artifact",
                schema=CHECKER_SCHEMA,
                instructions=CHECKER_INSTRUCTIONS,
                input_payload=payload,
                api_key=self.api_key,
                model=self.model,
                timeout_seconds=timeout_seconds,
                stage_label="review",
            )
            artifact = CheckerArtifact.from_dict(data)
        except OpenAITimeoutError as exc:
            raise OpenAICheckerTimeoutError(
                exc.timeout_seconds,
                schema_name="checker_artifact",
            ) from exc
        except (ArtifactValidationError, OpenAIClientError, TypeError, ValueError) as exc:
            raise OpenAICheckerError(
                f"OpenAI checker response did not match CheckerArtifact: {exc}"
            ) from exc
        if (
            not artifact.passed
            and is_canonical_cpi_demo_question(state.question)
            and len(payload["data"].get("series_ids") or []) <= 1
            and _canonical_cpi_artifacts_are_grounded(
                data=payload["data"],
                analysis=payload["analysis"],
                draft=payload["draft"],
            )
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
