"""Answer checkpoints for reference-based grounding."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from harness.checkpoints.base import CheckpointResult


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
    """Stub checkpoint reserved for success-criteria validation."""

    def evaluate(self, draft: Any, analysis: Any | None = None) -> CheckpointResult:
        return CheckpointResult.pass_result("Success criteria stub passed.")


def _read_field(item: Any, field_name: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(field_name)
    return getattr(item, field_name, None)
