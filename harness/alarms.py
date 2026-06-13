"""Alarm data model for harness failures and routing decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Alarm:
    """Serializable alarm used by the orchestrator to route failures."""

    type: str
    severity: str
    stage: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)
    recommended_action: str = "retry"
    retry_from: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "severity": self.severity,
            "stage": _string_value(self.stage),
            "message": self.message,
            "context": self.context,
            "recommended_action": self.recommended_action,
            "retry_from": self.retry_from,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Alarm":
        return cls(
            type=str(data["type"]),
            severity=str(data["severity"]),
            stage=str(data["stage"]),
            message=str(data["message"]),
            context=dict(data.get("context") or {}),
            recommended_action=str(data.get("recommended_action", "retry")),
            retry_from=str(data.get("retry_from", "")),
        )


def _string_value(value: Any) -> str:
    return str(getattr(value, "value", value))
