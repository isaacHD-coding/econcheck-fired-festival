"""Planning guardrails for structured plans and approved tool usage."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from harness.guardrails.base import GuardrailResult
from workers.artifacts import ArtifactValidationError, PlannerArtifact


REQUIRED_PLANNER_FIELDS = (
    "question_type",
    "economic_concepts",
    "measurement_strategy",
    "information_requirements",
    "search_queries",
    "required_outputs",
    "success_criteria",
)

APPROVED_TOOLS = {"FRED_SEARCH", "FRED_FETCH", "RUN_ANALYSIS_CODE"}
OPTIONAL_TOOL_FIELDS = ("tools", "tool_requests", "required_tools")


class PlannerSchemaGuardrail:
    """Validate the required PlannerArtifact schema before execution."""

    def evaluate(self, plan: Any) -> GuardrailResult:
        try:
            PlannerArtifact.from_dict(_planner_mapping(plan))
        except (ArtifactValidationError, TypeError, ValueError) as exc:
            return GuardrailResult.fail_result(
                guardrail_name=self.__class__.__name__,
                stage="planning",
                message=f"Planner artifact schema is invalid: {exc}",
                recommended_action="retry",
                retry_from="planning",
                context={"error": str(exc)},
            )

        return GuardrailResult.pass_result("Planner artifact schema is valid.")


class ApprovedToolGuardrail:
    """Allow only harness-approved tool requests in optional planner fields."""

    def evaluate(self, plan: Any) -> GuardrailResult:
        referenced_tools: list[str] = []

        # TODO: future planner schema should include explicit tool requests.
        for field_name in OPTIONAL_TOOL_FIELDS:
            present, value = _read_optional_field(plan, field_name)
            if present:
                referenced_tools.extend(_tool_names(value))

        unapproved_tools = [
            tool for tool in referenced_tools if tool.upper() not in APPROVED_TOOLS
        ]
        if unapproved_tools:
            return GuardrailResult.fail_result(
                guardrail_name=self.__class__.__name__,
                stage="planning",
                message="Planner referenced unapproved tools.",
                recommended_action="retry",
                retry_from="planning",
                context={
                    "approved_tools": sorted(APPROVED_TOOLS),
                    "unapproved_tools": unapproved_tools,
                },
            )

        return GuardrailResult.pass_result("Planner tool references are approved.")


def _planner_mapping(plan: Any) -> Mapping[str, Any]:
    if isinstance(plan, PlannerArtifact):
        return plan.to_dict()
    if isinstance(plan, Mapping):
        return plan
    if hasattr(plan, "to_dict"):
        data = plan.to_dict()
        if isinstance(data, Mapping):
            return data

    return {
        field_name: getattr(plan, field_name)
        for field_name in REQUIRED_PLANNER_FIELDS
        if hasattr(plan, field_name)
    }


def _read_optional_field(plan: Any, field_name: str) -> tuple[bool, Any]:
    if isinstance(plan, Mapping):
        if field_name in plan:
            return True, plan[field_name]
        return False, None

    if hasattr(plan, field_name):
        return True, getattr(plan, field_name)
    return False, None


def _tool_names(value: Any) -> list[str]:
    return [_tool_name(item) for item in _as_items(value)]


def _as_items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def _tool_name(item: Any) -> str:
    if isinstance(item, bytes):
        return item.decode("utf-8", errors="replace").strip()
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, Mapping):
        for key in ("tool", "name", "tool_name"):
            value = item.get(key)
            if isinstance(value, str):
                return value.strip()
        return str(item)

    for attr_name in ("tool", "name", "tool_name"):
        value = getattr(item, attr_name, None)
        if isinstance(value, str):
            return value.strip()
    return str(item)
