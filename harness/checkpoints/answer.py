"""Answer checkpoints for reference-based grounding."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from harness.checkpoints.base import CheckpointResult
from harness.domain import is_cpi_question


class AnswerGroundingCheckpoint:
    """Validate DraftArtifact metric references against AnalysisArtifact metrics."""

    def evaluate(self, draft: Any, analysis: Any) -> CheckpointResult:
        referenced_metrics = _read_field(draft, "referenced_metrics")
        metrics = _read_field(analysis, "metrics")

        if not isinstance(referenced_metrics, list) or not isinstance(metrics, list):
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="draft_answer",
                message="Draft metric references or analysis metrics are invalid.",
                retry_from="draft_answer",
            )

        available_metrics = {
            name
            for metric in metrics
            for name in [_read_field(metric, "name")]
            if isinstance(name, str)
        }
        if not referenced_metrics:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="draft_answer",
                message="Draft answer must reference generated metric names.",
                retry_from="draft_answer",
                context={"available_metrics": sorted(available_metrics)},
            )

        missing = [
            metric_name
            for metric_name in referenced_metrics
            if metric_name not in available_metrics
        ]
        if missing:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="draft_answer",
                message="Draft references metrics that are not in the analysis artifact.",
                retry_from="draft_answer",
                context={
                    "missing_metrics": missing,
                    "available_metrics": sorted(available_metrics),
                },
            )

        return CheckpointResult.pass_result("Draft metric references are grounded.")


class SuccessCriteriaCheckpoint:
    """Require a non-empty grounded answer that covers plan-level success criteria."""

    def evaluate(
        self,
        draft: Any,
        analysis: Any | None = None,
        plan: Any | None = None,
        question: str = "",
    ) -> CheckpointResult:
        answer = str(_read_field(draft, "answer") or "").strip()
        referenced = _read_field(draft, "referenced_metrics") or []
        criteria = list(_read_field(plan, "success_criteria") or []) if plan is not None else []
        needs_cpi = is_cpi_question(question) or any("cpi" in str(item).lower() for item in criteria)

        if not answer or not referenced:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="draft_answer",
                message="Draft answer must include grounded metric references.",
                retry_from="draft_answer",
                context={"success_criteria": criteria},
            )
        if needs_cpi and "cpi" not in answer.lower():
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="draft_answer",
                message="CPI questions must produce an answer that cites CPI evidence.",
                retry_from="draft_answer",
                context={"success_criteria": criteria},
            )
        if criteria and not all(str(item).strip() for item in criteria):
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="draft_answer",
                message="Plan success criteria are missing or empty.",
                retry_from="planning",
                context={"success_criteria": criteria},
            )

        return CheckpointResult.pass_result("Draft answer satisfies the plan success criteria.")


def _read_field(item: Any, field_name: str) -> Any:
    if item is None:
        return None
    if isinstance(item, Mapping):
        return item.get(field_name)
    return getattr(item, field_name, None)
