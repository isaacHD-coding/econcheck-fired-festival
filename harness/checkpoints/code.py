"""Code checkpoints for execution and output shape."""

from __future__ import annotations

from collections.abc import Mapping
import math
import re
from typing import Any

from harness.charts import would_dwarf_a_series, y_fields
from harness.checkpoints.base import CheckpointResult
from workers.artifacts import AnalysisArtifact, ArtifactValidationError, ChartBriefArtifact, CodeArtifact


# Prompt target is ~80–120 lines. This fail-closed ceiling is high enough for
# local analysis templates (relationship ~263 nonempty lines) but rejects the
# kitchen-sink stdlib scripts that stalled OpenAI JSON completion.
MAX_ANALYSIS_CODE_NONEMPTY_LINES = 300
MAX_ANALYSIS_CODE_HELPERS = 8
MAX_ANALYSIS_CODE_CHARS = 14000
_HELPER_DEF_RE = re.compile(r"^\s*def\s+\w+", re.MULTILINE)


class CodeSimplicityCheckpoint:
    """Reject over-engineered analysis scripts before the sandbox runs them."""

    def evaluate(self, code_artifact: Any) -> CheckpointResult:
        code = _read_analysis_code(code_artifact)
        stats = analysis_code_stats(code)
        reasons: list[str] = []
        if stats["nonempty_lines"] > MAX_ANALYSIS_CODE_NONEMPTY_LINES:
            reasons.append(
                f"{stats['nonempty_lines']} nonempty lines "
                f"(max {MAX_ANALYSIS_CODE_NONEMPTY_LINES})"
            )
        if stats["helpers"] > MAX_ANALYSIS_CODE_HELPERS:
            reasons.append(
                f"{stats['helpers']} helper functions "
                f"(max {MAX_ANALYSIS_CODE_HELPERS})"
            )
        if stats["chars"] > MAX_ANALYSIS_CODE_CHARS:
            reasons.append(
                f"{stats['chars']} characters (max {MAX_ANALYSIS_CODE_CHARS})"
            )
        if reasons:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="code_generation",
                message=(
                    "Generated analysis code is too large. Write a short "
                    "claim-focused script (about 80–120 lines, few helpers) "
                    "that computes the metrics the question needs plus one "
                    "chart. Follow chart_brief; do not re-implement alignment "
                    "frameworks, Pearson/median batteries, or missing-month "
                    "audits unless asked. "
                    + "; ".join(reasons)
                    + "."
                ),
                retry_from="code_generation",
                context=stats,
            )
        return CheckpointResult.pass_result("Analysis code stays within size limits.")


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
    """Require numeric metrics to be finite and present."""

    def evaluate(self, analysis: Any) -> CheckpointResult:
        metrics = _read_field(analysis, "metrics", [])
        if not isinstance(metrics, list):
            metrics = []
        values = [
            metric.get("value")
            for metric in metrics
            if isinstance(metric, dict) and isinstance(metric.get("value"), (int, float))
        ]
        if not values or any(not math.isfinite(value) for value in values):
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="code_generation",
                message="Metric values must be finite numbers.",
                retry_from="code_generation",
                context={"metric_values": values},
            )
        return CheckpointResult.pass_result("Metric values are finite.")


class ChartPromiseCheckpoint:
    """Require analysis output to include chart descriptor data."""

    def evaluate(self, analysis: Any) -> CheckpointResult:
        charts = _read_field(analysis, "charts", [])
        if not isinstance(charts, list) or not charts:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="code_generation",
                message="Analysis must include chart descriptor data.",
                retry_from="code_generation",
            )
        descriptors = [
            chart
            for chart in charts
            if isinstance(chart, dict) and isinstance(chart.get("data"), list)
        ]
        if not descriptors:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="code_generation",
                message=(
                    "Analysis charts must be a list of descriptors with a data "
                    "array of dated rows. Do not use nested charts[].series."
                ),
                retry_from="code_generation",
            )
        return CheckpointResult.pass_result("Analysis includes chart descriptor data.")


class ChartHonestyCheckpoint:
    """Reject shared-axis overlays that would dwarf a series."""

    def evaluate(self, analysis: Any) -> CheckpointResult:
        charts = _read_field(analysis, "charts", [])
        if not isinstance(charts, list):
            charts = []
        dwarfing = [
            index
            for index, chart in enumerate(charts)
            if isinstance(chart, dict) and would_dwarf_a_series(chart)
        ]
        if dwarfing:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="code_generation",
                message=(
                    "Chart places incompatible scales on one shared axis in a way "
                    "that would dwarf a series."
                ),
                retry_from="code_generation",
                context={"dwarfing_chart_indexes": dwarfing},
            )
        return CheckpointResult.pass_result("Charts do not dwarf a series on a shared axis.")


class ChartLabelCheckpoint:
    """Require units and series ids on multi-series charts."""

    def evaluate(self, analysis: Any) -> CheckpointResult:
        charts = _read_field(analysis, "charts", [])
        if not isinstance(charts, list):
            charts = []
        unlabeled = []
        for index, chart in enumerate(charts):
            if not isinstance(chart, dict) or not _is_multi_series_chart(chart):
                continue
            missing: list[str] = []
            if not _chart_has_units(chart):
                missing.append("units")
            if not _chart_cites_series_ids(chart):
                missing.append("series_ids")
            if missing:
                unlabeled.append({"index": index, "missing": missing})
        if unlabeled:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="code_generation",
                message="Multi-series charts must label units and cite FRED series ids.",
                retry_from="code_generation",
                context={"unlabeled_charts": unlabeled},
            )
        return CheckpointResult.pass_result("Multi-series charts label units and series ids.")


class ChartBriefCheckpoint:
    """Require a validated chart brief, especially for multi-series paths."""

    def evaluate(
        self,
        chart_brief: Any,
        data: Any = None,
        *,
        question: str = "",
    ) -> CheckpointResult:
        try:
            brief = _as_chart_brief(chart_brief)
        except (ArtifactValidationError, AttributeError, TypeError, ValueError) as exc:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="code_generation",
                message=f"Chart brief is missing or invalid: {exc}",
                retry_from="code_generation",
                context={"error": str(exc)},
            )

        fetched = _data_series_ids(data)
        invented = [series_id for series_id in brief.series_ids if fetched and series_id not in fetched]
        if invented:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="code_generation",
                message="Chart brief cites FRED series that were not fetched.",
                retry_from="code_generation",
                context={"invented_series_ids": invented, "fetched_series_ids": fetched},
            )
        if len(fetched) >= 2 and len([item for item in brief.series_ids if item in fetched]) < 2:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="code_generation",
                message="Multi-series analysis requires a chart brief covering the fetched series.",
                retry_from="code_generation",
                context={
                    "brief_series_ids": list(brief.series_ids),
                    "fetched_series_ids": fetched,
                    "question": question,
                },
            )
        return CheckpointResult.pass_result("Chart brief is present and validated.")


def analysis_code_stats(code: str) -> dict[str, int]:
    text = str(code or "")
    nonempty_lines = [line for line in text.splitlines() if line.strip()]
    return {
        "total_lines": len(text.splitlines()),
        "nonempty_lines": len(nonempty_lines),
        "helpers": len(_HELPER_DEF_RE.findall(text)),
        "chars": len(text),
    }


def _read_analysis_code(code_artifact: Any) -> str:
    if isinstance(code_artifact, str):
        return code_artifact
    if isinstance(code_artifact, CodeArtifact):
        return code_artifact.code
    code = _read_field(code_artifact, "code", "")
    return str(code or "")


def _read_field(item: Any, field_name: str, default: Any = None) -> Any:
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


def _is_multi_series_chart(chart: dict[str, Any]) -> bool:
    if len(y_fields(chart)) >= 2:
        return True
    series_ids = _chart_series_ids(chart)
    return len(series_ids) >= 2


def _chart_has_units(chart: dict[str, Any]) -> bool:
    for key in ("unit", "units", "y_label"):
        if str(chart.get(key) or "").strip():
            return True
    left = str(chart.get("y_left_label") or "").strip()
    right = str(chart.get("y_right_label") or "").strip()
    return bool(left and right)


def _chart_cites_series_ids(chart: dict[str, Any]) -> bool:
    if _chart_series_ids(chart):
        return True
    blob = " ".join(
        [
            str(chart.get("title") or ""),
            str(chart.get("notes") or ""),
            " ".join(y_fields(chart)),
        ]
    )
    return bool(_extract_series_tokens(blob))


def _chart_series_ids(chart: dict[str, Any]) -> list[str]:
    raw = chart.get("series_ids")
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    series_id = chart.get("series_id")
    if isinstance(series_id, list):
        return [str(item) for item in series_id if str(item).strip()]
    if isinstance(series_id, str) and series_id.strip():
        return [part.strip() for part in series_id.split(",") if part.strip()]
    return []


def _extract_series_tokens(blob: str) -> list[str]:
    tokens = []
    for token in blob.replace(",", " ").split():
        cleaned = token.strip("()[]")
        if cleaned.isupper() and any(char.isdigit() for char in cleaned) and len(cleaned) >= 4:
            tokens.append(cleaned)
    return tokens


def _as_chart_brief(chart_brief: Any) -> ChartBriefArtifact:
    if isinstance(chart_brief, ChartBriefArtifact):
        return ChartBriefArtifact.from_dict(chart_brief.to_dict())
    if hasattr(chart_brief, "to_dict"):
        return ChartBriefArtifact.from_dict(chart_brief.to_dict())
    if isinstance(chart_brief, Mapping):
        return ChartBriefArtifact.from_dict(chart_brief)
    raise ArtifactValidationError("chart_brief is required")


def _data_series_ids(data: Any) -> list[str]:
    if data is None:
        return []
    series_ids = _read_field(data, "series_ids", [])
    if isinstance(series_ids, list) and series_ids:
        return [str(item) for item in series_ids]
    observations = _read_field(data, "observations", {})
    if isinstance(observations, dict):
        return [str(item) for item in observations]
    return []
