import tempfile
import unittest

from harness.alarms import Alarm
from harness.orchestrator import Orchestrator
from harness.persistence import load_run_state
from harness.state import RunState, Stage


def retry_alarm(retry_from: str = "code_generation") -> Alarm:
    return Alarm(
        type="checkpoint_failed",
        severity="warning",
        stage=retry_from,
        message="Retry the failed stage.",
        context={},
        recommended_action="retry",
        retry_from=retry_from,
    )


class OrchestratorTests(unittest.TestCase):
    def test_run_advances_linear_flow_to_released(self) -> None:
        state = RunState(
            run_id="run-1",
            question="What happened to CPI?",
            current_stage=Stage.INPUT,
            retry_count=0,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            final_state = Orchestrator(state, tmpdir).run()
            persisted_state = load_run_state("run-1", tmpdir)

        self.assertIs(final_state.current_stage, Stage.RELEASED)
        self.assertIs(persisted_state.current_stage, Stage.RELEASED)

    def test_advance_stage_moves_through_expected_route(self) -> None:
        state = RunState(
            run_id="run-1",
            question="What happened to CPI?",
            current_stage=Stage.INPUT,
            retry_count=0,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = Orchestrator(state, tmpdir)
            observed = []
            while orchestrator.state.current_stage is not Stage.RELEASED:
                orchestrator.advance_stage()
                observed.append(orchestrator.state.current_stage)

        self.assertEqual(
            observed,
            [
                Stage.PLANNING,
                Stage.DATA_DISCOVERY,
                Stage.CODE_GENERATION,
                Stage.DRAFT_ANSWER,
                Stage.CHECKER_REVIEW,
                Stage.RELEASED,
            ],
        )

    def test_retry_routes_to_alarm_retry_target_and_then_can_release(self) -> None:
        state = RunState(
            run_id="run-1",
            question="What happened to CPI?",
            current_stage=Stage.CODE_GENERATION,
            retry_count=0,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = Orchestrator(state, tmpdir)
            retried_state = orchestrator.retry(retry_alarm("code_generation"))
            retry_stage = retried_state.current_stage
            released_state = orchestrator.release()

        self.assertIs(retry_stage, Stage.CODE_GENERATION)
        self.assertIs(released_state.current_stage, Stage.RELEASED)
        self.assertEqual(released_state.retry_count, 1)
        self.assertEqual(released_state.alarms[0].retry_from, "code_generation")

    def test_retry_argument_overrides_alarm_retry_target(self) -> None:
        state = RunState(
            run_id="run-1",
            question="What happened to CPI?",
            current_stage=Stage.CHECKER_REVIEW,
            retry_count=0,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = Orchestrator(state, tmpdir)
            retried_state = orchestrator.retry(
                retry_alarm("planning"),
                retry_from="draft_answer",
            )

        self.assertIs(retried_state.current_stage, Stage.DRAFT_ANSWER)

    def test_retry_count_equal_to_max_turns_does_not_escalate(self) -> None:
        state = RunState(
            run_id="run-1",
            question="What happened to CPI?",
            current_stage=Stage.CODE_GENERATION,
            retry_count=4,
            max_turns=5,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            retried_state = Orchestrator(state, tmpdir).retry(
                retry_alarm("code_generation")
            )

        self.assertIs(retried_state.current_stage, Stage.CODE_GENERATION)
        self.assertEqual(retried_state.retry_count, 5)

    def test_retry_count_above_max_turns_escalates(self) -> None:
        state = RunState(
            run_id="run-1",
            question="What happened to CPI?",
            current_stage=Stage.CODE_GENERATION,
            retry_count=5,
            max_turns=5,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            escalated_state = Orchestrator(state, tmpdir).retry(
                retry_alarm("code_generation")
            )

        self.assertIs(escalated_state.current_stage, Stage.ESCALATED)
        self.assertEqual(escalated_state.retry_count, 6)

    def test_escalate_moves_to_terminal_stage_and_persists_alarm(self) -> None:
        state = RunState(
            run_id="run-1",
            question="What happened to CPI?",
            current_stage=Stage.PLANNING,
            retry_count=0,
        )
        alarm = retry_alarm("planning")

        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = Orchestrator(state, tmpdir)
            escalated_state = orchestrator.escalate(alarm)
            persisted_state = load_run_state("run-1", tmpdir)

        self.assertIs(escalated_state.current_stage, Stage.ESCALATED)
        self.assertEqual(persisted_state.alarms[0].retry_from, "planning")

    def test_unknown_retry_target_raises_value_error(self) -> None:
        state = RunState(
            run_id="run-1",
            question="What happened to CPI?",
            current_stage=Stage.CODE_GENERATION,
            retry_count=0,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = Orchestrator(state, tmpdir)
            with self.assertRaises(ValueError):
                orchestrator.retry(retry_from="checker_review")


if __name__ == "__main__":
    unittest.main()
