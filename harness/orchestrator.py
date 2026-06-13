"""Orchestrator skeleton for EconCheck run control."""

from __future__ import annotations

from pathlib import Path

from harness.alarms import Alarm
from harness.persistence import save_run_state
from harness.state import RunState, Stage


TERMINAL_STAGES = {Stage.RELEASED, Stage.ESCALATED}

NEXT_STAGE = {
    Stage.INPUT: Stage.PLANNING,
    Stage.PLANNING: Stage.DATA_DISCOVERY,
    Stage.DATA_DISCOVERY: Stage.CODE_GENERATION,
    Stage.CODE_GENERATION: Stage.DRAFT_ANSWER,
    Stage.DRAFT_ANSWER: Stage.CHECKER_REVIEW,
    Stage.CHECKER_REVIEW: Stage.RELEASED,
}

RETRY_STAGES = {
    "planning": Stage.PLANNING,
    "data_discovery": Stage.DATA_DISCOVERY,
    "code_generation": Stage.CODE_GENERATION,
    "draft_answer": Stage.DRAFT_ANSWER,
}


class Orchestrator:
    """Owns stage progression, retries, escalation, and release decisions."""

    def __init__(self, state: RunState, runs_dir: str | Path = "runs") -> None:
        self.state = state
        self.runs_dir = Path(runs_dir)
        self._persist()

    def run(self) -> RunState:
        while self.state.current_stage not in TERMINAL_STAGES:
            self.advance_stage()
        return self.state

    def advance_stage(self) -> RunState:
        if self.state.current_stage in TERMINAL_STAGES:
            return self.state

        next_stage = NEXT_STAGE.get(self.state.current_stage)
        if next_stage is None:
            return self.escalate()

        if next_stage is Stage.RELEASED:
            return self.release()

        self.state.current_stage = next_stage
        self._persist()
        return self.state

    def retry(self, alarm: Alarm | None = None, retry_from: str | Stage | None = None) -> RunState:
        if alarm is not None:
            self.state.alarms.append(alarm)

        self.state.retry_count += 1
        if self.state.retry_count > self.state.max_turns:
            return self.escalate(alarm)

        target = retry_from
        if target is None and alarm is not None:
            target = alarm.retry_from

        self.state.current_stage = self._normalize_retry_stage(target)
        self._persist()
        return self.state

    def route_alarm(self, alarm: Alarm) -> RunState:
        if alarm.recommended_action == "retry":
            return self.retry(alarm)
        if alarm.recommended_action == "escalate":
            return self.escalate(alarm)
        if alarm.recommended_action == "abort":
            return self.abort(alarm)

        raise ValueError(f"Unknown alarm action: {alarm.recommended_action!r}")

    def release(self) -> RunState:
        self.state.current_stage = Stage.RELEASED
        self._persist()
        return self.state

    def escalate(self, alarm: Alarm | None = None) -> RunState:
        if alarm is not None and alarm not in self.state.alarms:
            self.state.alarms.append(alarm)
        self.state.current_stage = Stage.ESCALATED
        self._persist()
        return self.state

    def abort(self, alarm: Alarm | None = None) -> RunState:
        if alarm is not None and alarm not in self.state.alarms:
            self.state.alarms.append(alarm)
        self.state.current_stage = Stage.ESCALATED
        self._persist()
        return self.state

    def _persist(self) -> None:
        save_run_state(self.state, self.runs_dir)

    def _normalize_retry_stage(self, retry_from: str | Stage | None) -> Stage:
        if retry_from is None:
            return self.state.current_stage
        if isinstance(retry_from, Stage):
            return retry_from

        try:
            return RETRY_STAGES[retry_from]
        except KeyError as exc:
            raise ValueError(f"Unknown retry target: {retry_from!r}") from exc
