"""Guardrail registry for the EconCheck harness."""

from harness.guardrails.base import GuardrailResult
from harness.guardrails.input import (
    DataSecurityGuardrail,
    EconomicScopeGuardrail,
    FredAnswerableGuardrail,
    PromptInjectionGuardrail,
)
from harness.guardrails.planning import (
    ApprovedToolGuardrail,
    PlannerSchemaGuardrail,
)


INPUT_GUARDRAILS = (
    EconomicScopeGuardrail(),
    FredAnswerableGuardrail(),
    PromptInjectionGuardrail(),
    DataSecurityGuardrail(),
)

PLANNING_GUARDRAILS = (
    PlannerSchemaGuardrail(),
    ApprovedToolGuardrail(),
)

GUARDRAIL_REGISTRY = {
    "input": INPUT_GUARDRAILS,
    "planning": PLANNING_GUARDRAILS,
}


__all__ = [
    "ApprovedToolGuardrail",
    "DataSecurityGuardrail",
    "EconomicScopeGuardrail",
    "FredAnswerableGuardrail",
    "GUARDRAIL_REGISTRY",
    "GuardrailResult",
    "INPUT_GUARDRAILS",
    "PLANNING_GUARDRAILS",
    "PlannerSchemaGuardrail",
    "PromptInjectionGuardrail",
]
