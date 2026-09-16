"""Worker-facing artifact schemas for EconCheck."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class ArtifactValidationError(ValueError):
    """Raised when an artifact does not match its required schema."""


@dataclass
class PlannerArtifact:
    question_type: str
    economic_concepts: list[str]
    measurement_strategy: str
    information_requirements: list[str]
    search_queries: list[str]
    required_outputs: list[str]
    success_criteria: list[str]

    def __post_init__(self) -> None:
        _require_non_empty_string("question_type", self.question_type)
        _require_non_empty_string("measurement_strategy", self.measurement_strategy)
        _require_non_empty_string_list("economic_concepts", self.economic_concepts)
        _require_non_empty_string_list(
            "information_requirements",
            self.information_requirements,
        )
        _require_non_empty_string_list("search_queries", self.search_queries)
        _require_non_empty_string_list("required_outputs", self.required_outputs)
        _require_non_empty_string_list("success_criteria", self.success_criteria)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_type": self.question_type,
            "economic_concepts": list(self.economic_concepts),
            "measurement_strategy": self.measurement_strategy,
            "information_requirements": list(self.information_requirements),
            "search_queries": list(self.search_queries),
            "required_outputs": list(self.required_outputs),
            "success_criteria": list(self.success_criteria),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlannerArtifact":
        _require_mapping(data)
        return cls(
            question_type=_required(data, "question_type"),
            economic_concepts=_required(data, "economic_concepts"),
            measurement_strategy=_required(data, "measurement_strategy"),
            information_requirements=_required(data, "information_requirements"),
            search_queries=_required(data, "search_queries"),
            required_outputs=_required(data, "required_outputs"),
            success_criteria=_required(data, "success_criteria"),
        )


@dataclass
class DataSelectionArtifact:
    selected_series: list[dict]
    rejected_series: list[dict]
    justification: str

    def __post_init__(self) -> None:
        _require_list_of_dicts("selected_series", self.selected_series)
        _require_list_of_dicts("rejected_series", self.rejected_series)
        _require_string("justification", self.justification)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_series": [dict(item) for item in self.selected_series],
            "rejected_series": [dict(item) for item in self.rejected_series],
            "justification": self.justification,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DataSelectionArtifact":
        _require_mapping(data)
        return cls(
            selected_series=_required(data, "selected_series"),
            rejected_series=_required(data, "rejected_series"),
            justification=_required(data, "justification"),
        )


@dataclass
class DataArtifact:
    series_ids: list[str]
    observations: dict[str, list[dict[str, Any]]]
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        _require_string_list("series_ids", self.series_ids)
        _require_dict("observations", self.observations)
        for series_id, rows in self.observations.items():
            _require_string("observations key", series_id)
            _require_list_of_dicts(f"observations[{series_id}]", rows)
        _require_dict("metadata", self.metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "series_ids": list(self.series_ids),
            "observations": {
                series_id: [dict(row) for row in rows]
                for series_id, rows in self.observations.items()
            },
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DataArtifact":
        _require_mapping(data)
        return cls(
            series_ids=_required(data, "series_ids"),
            observations=_required(data, "observations"),
            metadata=_required(data, "metadata"),
        )


@dataclass
class CodeArtifact:
    code: str

    def __post_init__(self) -> None:
        _require_non_empty_string("code", self.code)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CodeArtifact":
        _require_mapping(data)
        return cls(code=_required(data, "code"))


ALLOWED_CHART_LAYOUTS = {"single", "dual_axis", "stacked"}
ALLOWED_CHART_TYPES = {"line", "scatter", "bars", "panels"}


@dataclass
class ChartBriefArtifact:
    claim: str
    series_ids: list[str]
    transforms: list[str]
    layout: str
    y_starts_at_zero: bool
    time_window_rationale: str
    annotations: list[str]
    title: str
    x_label: str
    y_label: str
    units: str
    notes: str
    chart_type: str
    y_left_label: str = ""
    y_right_label: str = ""
    design_notes: str = ""

    def __post_init__(self) -> None:
        _require_non_empty_string("claim", self.claim)
        _require_string_list("series_ids", self.series_ids)
        for index, series_id in enumerate(self.series_ids):
            if series_id.strip() == "":
                raise ArtifactValidationError(f"series_ids[{index}] must be non-empty")
        _require_non_empty_string_list("transforms", self.transforms)
        _require_non_empty_string("layout", self.layout)
        self.layout = self.layout.strip().lower().replace("-", "_").replace(" ", "_")
        layout_aliases = {
            "small_multiples": "stacked",
            "small_multiple": "stacked",
            "panels": "stacked",
            "dual": "dual_axis",
            "growth_overlay": "single",
        }
        self.layout = layout_aliases.get(self.layout, self.layout)
        if self.layout not in ALLOWED_CHART_LAYOUTS:
            allowed = ", ".join(sorted(ALLOWED_CHART_LAYOUTS))
            raise ArtifactValidationError(f"layout must be one of: {allowed}")
        if not isinstance(self.y_starts_at_zero, bool):
            raise ArtifactValidationError("y_starts_at_zero must be a bool")
        _require_non_empty_string("time_window_rationale", self.time_window_rationale)
        _require_string_list("annotations", self.annotations)
        _require_non_empty_string("title", self.title)
        _require_non_empty_string("x_label", self.x_label)
        _require_non_empty_string("y_label", self.y_label)
        _require_non_empty_string("units", self.units)
        _require_non_empty_string("notes", self.notes)
        _require_non_empty_string("chart_type", self.chart_type)
        self.chart_type = self.chart_type.strip().lower()
        chart_type_aliases = {"bar": "bars", "scatterplot": "scatter", "panel": "panels"}
        self.chart_type = chart_type_aliases.get(self.chart_type, self.chart_type)
        if self.chart_type not in ALLOWED_CHART_TYPES:
            allowed = ", ".join(sorted(ALLOWED_CHART_TYPES))
            raise ArtifactValidationError(f"chart_type must be one of: {allowed}")
        _require_string("y_left_label", self.y_left_label)
        _require_string("y_right_label", self.y_right_label)
        _require_string("design_notes", self.design_notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "series_ids": list(self.series_ids),
            "transforms": list(self.transforms),
            "layout": self.layout,
            "y_starts_at_zero": self.y_starts_at_zero,
            "time_window_rationale": self.time_window_rationale,
            "annotations": list(self.annotations),
            "title": self.title,
            "x_label": self.x_label,
            "y_label": self.y_label,
            "units": self.units,
            "notes": self.notes,
            "chart_type": self.chart_type,
            "y_left_label": self.y_left_label,
            "y_right_label": self.y_right_label,
            "design_notes": self.design_notes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChartBriefArtifact":
        _require_mapping(data)
        return cls(
            claim=_required(data, "claim"),
            series_ids=_required(data, "series_ids"),
            transforms=_required(data, "transforms"),
            layout=_required(data, "layout"),
            y_starts_at_zero=_required(data, "y_starts_at_zero"),
            time_window_rationale=_required(data, "time_window_rationale"),
            annotations=_required(data, "annotations"),
            title=_required(data, "title"),
            x_label=data.get("x_label") or "date",
            y_label=_required(data, "y_label"),
            units=_required(data, "units"),
            notes=_required(data, "notes"),
            chart_type=_required(data, "chart_type"),
            y_left_label=data.get("y_left_label") or "",
            y_right_label=data.get("y_right_label") or "",
            design_notes=data.get("design_notes") or "",
        )


@dataclass
class AnalysisArtifact:
    tables: list
    metrics: list
    claims: list
    charts: list
    method_notes: str
    warnings: list

    def __post_init__(self) -> None:
        _require_list("tables", self.tables)
        _require_list("metrics", self.metrics)
        _require_list("claims", self.claims)
        _require_list("charts", self.charts)
        _require_string("method_notes", self.method_notes)
        _require_list("warnings", self.warnings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tables": list(self.tables),
            "metrics": list(self.metrics),
            "claims": list(self.claims),
            "charts": list(self.charts),
            "method_notes": self.method_notes,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AnalysisArtifact":
        _require_mapping(data)
        return cls(
            tables=_required(data, "tables"),
            metrics=_required(data, "metrics"),
            claims=_required(data, "claims"),
            charts=_required(data, "charts"),
            method_notes=_required(data, "method_notes"),
            warnings=_required(data, "warnings"),
        )


@dataclass
class DraftArtifact:
    answer: str
    referenced_metrics: list[str]
    chart_paths: list[str]

    def __post_init__(self) -> None:
        _require_string("answer", self.answer)
        _require_string_list("referenced_metrics", self.referenced_metrics)
        _require_string_list("chart_paths", self.chart_paths)

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "referenced_metrics": list(self.referenced_metrics),
            "chart_paths": list(self.chart_paths),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DraftArtifact":
        _require_mapping(data)
        return cls(
            answer=_required(data, "answer"),
            referenced_metrics=_required(data, "referenced_metrics"),
            chart_paths=_required(data, "chart_paths"),
        )


@dataclass
class CheckerArtifact:
    passed: bool
    issues: list[str]
    retry_from: str
    explanation: str

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise ArtifactValidationError("passed must be a bool")
        _require_string_list("issues", self.issues)
        _require_retry_from("retry_from", self.retry_from)
        _require_string("explanation", self.explanation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": list(self.issues),
            "retry_from": self.retry_from,
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CheckerArtifact":
        _require_mapping(data)
        return cls(
            passed=_required(data, "passed"),
            issues=_required(data, "issues"),
            retry_from=_required(data, "retry_from"),
            explanation=_required(data, "explanation"),
        )


def _require_mapping(data: Mapping[str, Any]) -> None:
    if not isinstance(data, Mapping):
        raise ArtifactValidationError("artifact data must be a mapping")


def _required(data: Mapping[str, Any], field_name: str) -> Any:
    if field_name not in data:
        raise ArtifactValidationError(f"{field_name} is required")
    return data[field_name]


def _require_string(field_name: str, value: Any) -> None:
    if not isinstance(value, str):
        raise ArtifactValidationError(f"{field_name} must be a string")


def _require_non_empty_string(field_name: str, value: Any) -> None:
    _require_string(field_name, value)
    if value.strip() == "":
        raise ArtifactValidationError(f"{field_name} must be non-empty")


def _require_list(field_name: str, value: Any) -> None:
    if not isinstance(value, list):
        raise ArtifactValidationError(f"{field_name} must be a list")


def _require_dict(field_name: str, value: Any) -> None:
    if not isinstance(value, dict):
        raise ArtifactValidationError(f"{field_name} must be a dict")


def _require_string_list(field_name: str, value: Any) -> None:
    _require_list(field_name, value)
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ArtifactValidationError(f"{field_name}[{index}] must be a string")


def _require_non_empty_string_list(field_name: str, value: Any) -> None:
    _require_string_list(field_name, value)
    if not value:
        raise ArtifactValidationError(f"{field_name} must be non-empty")
    for index, item in enumerate(value):
        if item.strip() == "":
            raise ArtifactValidationError(f"{field_name}[{index}] must be non-empty")


def _require_list_of_dicts(field_name: str, value: Any) -> None:
    _require_list(field_name, value)
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ArtifactValidationError(f"{field_name}[{index}] must be a dict")


def _require_retry_from(field_name: str, value: Any) -> None:
    _require_string(field_name, value)
    allowed_values = {"", "planning", "data_discovery", "code_generation", "draft_answer"}
    if value not in allowed_values:
        allowed = ", ".join(repr(item) for item in sorted(allowed_values))
        raise ArtifactValidationError(f"{field_name} must be one of: {allowed}")
