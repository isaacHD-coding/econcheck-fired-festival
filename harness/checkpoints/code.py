"""Code checkpoints for execution and output shape."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from harness.checkpoints.base import CheckpointResult
from workers.artifacts import AnalysisArtifact, ArtifactValidationError


class CodeExecutionCheckpoint:
    """Validate that analysis execution succeeded and has no recorded error."""

    def evaluate(self, execution_result: Any) -> CheckpointResult:
        if isinstance(execution_result, AnalysisArtifact):
            return CheckpointResult.pass_result("Analysis artifact implies execution success.")

        succeeded = _read_field(execution_result, "succeeded", True)
        execution_error = _read_field(execution_result, "execution_error", None)

        if succeeded is False or bool(execution_error):
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="code_generation",
                message="Analysis execution failed.",
                retry_from="code_generation",
                context={
                    "succeeded": succeeded,
                    "execution_error": execution_error,
                },
            )

        return CheckpointResult.pass_result("Analysis execution succeeded.")


class OutputShapeCheckpoint:
    """Require the complete AnalysisArtifact outer schema."""

    def evaluate(self, analysis: Any) -> CheckpointResult:
        try:
            if isinstance(analysis, AnalysisArtifact):
                AnalysisArtifact.from_dict(analysis.to_dict())
            else:
                AnalysisArtifact.from_dict(_analysis_mapping(analysis))
        except (ArtifactValidationError, AttributeError, TypeError, ValueError) as exc:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="code_generation",
                message=f"Analysis output shape is invalid: {exc}",
                retry_from="code_generation",
                context={"error": str(exc)},
            )

        return CheckpointResult.pass_result("Analysis output shape is valid.")


class MathSanityCheckpoint:
    """Stub checkpoint reserved for math sanity checks."""

    def evaluate(self, analysis: Any) -> CheckpointResult:
        return CheckpointResult.pass_result("Math sanity stub passed.")


class ChartPromiseCheckpoint:
    """Stub checkpoint reserved for chart promise checks."""

    def evaluate(self, analysis: Any) -> CheckpointResult:
        return CheckpointResult.pass_result("Chart promise stub passed.")


def _read_field(item: Any, field_name: str, default: Any) -> Any:
    if isinstance(item, Mapping):
        return item.get(field_name, default)
    return getattr(item, field_name, default)


def _analysis_mapping(analysis: Any) -> Mapping[str, Any]:
    if isinstance(analysis, Mapping):
        return analysis
    if hasattr(analysis, "to_dict"):
        data = analysis.to_dict()
        if isinstance(data, Mapping):
            return data

    required_fields = (
        "tables",
        "metrics",
        "claims",
        "charts",
        "method_notes",
        "warnings",
    )
    return {field_name: getattr(analysis, field_name) for field_name in required_fields}
