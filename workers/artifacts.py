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
    allowed_values = {"planning", "data_discovery", "code_generation", "draft_answer"}
    if value not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ArtifactValidationError(f"{field_name} must be one of: {allowed}")
