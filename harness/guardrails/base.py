"""Shared guardrail result helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from harness.alarms import Alarm


@dataclass(frozen=True)
class GuardrailResult:
    """Result returned by guardrails, including a routing alarm on failure."""

    passed: bool
    reason: str
    alarm: Alarm | None = None

    @classmethod
    def pass_result(cls, reason: str = "Guardrail passed.") -> "GuardrailResult":
        return cls(passed=True, reason=reason, alarm=None)

    @classmethod
    def fail_result(
        cls,
        *,
        guardrail_name: str,
        stage: str,
        message: str,
        recommended_action: str,
        retry_from: str = "",
        severity: str = "warning",
        context: dict[str, Any] | None = None,
    ) -> "GuardrailResult":
        alarm = Alarm(
            type=f"{_snake_case(guardrail_name)}_failed",
            severity=severity,
            stage=stage,
            message=message,
            context={"guardrail": guardrail_name, **(context or {})},
            recommended_action=recommended_action,
            retry_from=retry_from,
        )
        return cls(passed=False, reason=message, alarm=alarm)


def _snake_case(value: str) -> str:
    chars: list[str] = []
    for index, char in enumerate(value):
        if char.isupper() and index > 0:
            chars.append("_")
        chars.append(char.lower())
    return "".join(chars)
