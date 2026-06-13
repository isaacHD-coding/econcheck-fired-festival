"""Data checkpoints for evidence provenance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from harness.checkpoints.base import CheckpointResult


class SourceProvenanceCheckpoint:
    """Require every metric to carry source_series provenance."""

    def evaluate(self, analysis: Any) -> CheckpointResult:
        metrics = _read_field(analysis, "metrics")
        if not isinstance(metrics, list):
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="data_discovery",
                message="Analysis metrics are missing or invalid.",
                retry_from="code_generation",
                context={"field": "metrics"},
            )

        missing = [
            _metric_label(metric, index)
            for index, metric in enumerate(metrics)
            if not _has_field(metric, "source_series")
        ]
        if missing:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="data_discovery",
                message="One or more metrics are missing source_series provenance.",
                retry_from="code_generation",
                context={"missing_metrics": missing},
            )

        return CheckpointResult.pass_result(
            "Every metric includes source_series provenance."
        )


class DataCompletenessCheckpoint:
    """Stub checkpoint reserved for data completeness checks."""

    def evaluate(self, artifact: Any) -> CheckpointResult:
        return CheckpointResult.pass_result("Data completeness stub passed.")


class FreshnessCheckpoint:
    """Stub checkpoint reserved for data freshness checks."""

    def evaluate(self, artifact: Any) -> CheckpointResult:
        return CheckpointResult.pass_result("Freshness stub passed.")


class InformationSufficiencyCheckpoint:
    """Stub checkpoint reserved for information sufficiency checks."""

    def evaluate(self, artifact: Any) -> CheckpointResult:
        return CheckpointResult.pass_result("Information sufficiency stub passed.")


def _read_field(artifact: Any, field_name: str) -> Any:
    if isinstance(artifact, Mapping):
        return artifact.get(field_name)
    return getattr(artifact, field_name, None)


def _has_field(item: Any, field_name: str) -> bool:
    if isinstance(item, Mapping):
        return field_name in item
    return hasattr(item, field_name)


def _metric_label(metric: Any, index: int) -> str:
    name = _read_field(metric, "name")
    if isinstance(name, str) and name:
        return name
    return f"metric[{index}]"
