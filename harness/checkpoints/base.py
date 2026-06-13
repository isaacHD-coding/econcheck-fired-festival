"""Shared checkpoint result helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from harness.alarms import Alarm


@dataclass(frozen=True)
class CheckpointResult:
    """Checkpoint outcome, including the alarm that routes failures."""

    passed: bool
    alarm: Alarm | None = None
    reason: str = ""

    @classmethod
    def pass_result(cls, reason: str = "Checkpoint passed.") -> "CheckpointResult":
        return cls(passed=True, alarm=None, reason=reason)

    @classmethod
    def fail_result(
        cls,
        *,
        checkpoint_name: str,
        stage: str,
        message: str,
        retry_from: str,
        context: dict[str, Any] | None = None,
        recommended_action: str = "retry",
        severity: str = "warning",
    ) -> "CheckpointResult":
        alarm = Alarm(
            type=f"{_snake_case(checkpoint_name)}_failed",
            severity=severity,
            stage=stage,
            message=message,
            context={"checkpoint": checkpoint_name, **(context or {})},
            recommended_action=recommended_action,
            retry_from=retry_from,
        )
        return cls(passed=False, alarm=alarm, reason=message)


def _snake_case(value: str) -> str:
    chars: list[str] = []
    for index, char in enumerate(value):
        if char.isupper() and index > 0:
            chars.append("_")
        chars.append(char.lower())
    return "".join(chars)
