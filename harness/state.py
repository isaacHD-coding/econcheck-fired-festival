"""Core run state for the EconCheck harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from harness.alarms import Alarm


class Stage(Enum):
    INPUT = "input"
    PLANNING = "planning"
    DATA_DISCOVERY = "data_discovery"
    CODE_GENERATION = "code_generation"
    DRAFT_ANSWER = "draft_answer"
    CHECKER_REVIEW = "checker_review"
    RELEASED = "released"
    ESCALATED = "escalated"

    @classmethod
    def from_value(cls, value: "Stage | str") -> "Stage":
        if isinstance(value, cls):
            return value

        normalized = str(value).strip()
        for stage in cls:
            if normalized == stage.value or normalized == stage.name:
                return stage
            if normalized.lower() == stage.value or normalized.upper() == stage.name:
                return stage

        raise ValueError(f"Unknown stage: {value!r}")


@dataclass
class RunState:
    run_id: str
    question: str
    current_stage: Stage
    retry_count: int
    max_turns: int = 5
    artifacts: dict[str, Any] = field(default_factory=dict)
    alarms: list[Alarm] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "question": self.question,
            "current_stage": self.current_stage.value,
            "retry_count": self.retry_count,
            "max_turns": self.max_turns,
            "artifacts": self.artifacts,
            "alarms": [alarm.to_dict() for alarm in self.alarms],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunState":
        return cls(
            run_id=str(data["run_id"]),
            question=str(data["question"]),
            current_stage=Stage.from_value(data["current_stage"]),
            retry_count=int(data.get("retry_count", 0)),
            max_turns=int(data.get("max_turns", 5)),
            artifacts=dict(data.get("artifacts") or {}),
            alarms=[
                alarm if isinstance(alarm, Alarm) else Alarm.from_dict(alarm)
                for alarm in data.get("alarms", [])
            ],
        )
