import unittest

from harness.alarms import Alarm
from harness.state import RunState, Stage


class StateTests(unittest.TestCase):
    def test_stage_values_match_contract(self) -> None:
        self.assertEqual(Stage.INPUT.value, "input")
        self.assertEqual(Stage.PLANNING.value, "planning")
        self.assertEqual(Stage.DATA_DISCOVERY.value, "data_discovery")
        self.assertEqual(Stage.CODE_GENERATION.value, "code_generation")
        self.assertEqual(Stage.DRAFT_ANSWER.value, "draft_answer")
        self.assertEqual(Stage.CHECKER_REVIEW.value, "checker_review")
        self.assertEqual(Stage.RELEASED.value, "released")
        self.assertEqual(Stage.ESCALATED.value, "escalated")

    def test_stage_from_value_accepts_enum_values_and_names(self) -> None:
        self.assertIs(Stage.from_value(Stage.INPUT), Stage.INPUT)
        self.assertIs(Stage.from_value("planning"), Stage.PLANNING)
        self.assertIs(Stage.from_value("DATA_DISCOVERY"), Stage.DATA_DISCOVERY)

    def test_stage_from_value_rejects_unknown_stage(self) -> None:
        with self.assertRaises(ValueError):
            Stage.from_value("unsupported")

    def test_run_state_serializes_to_json_safe_dictionary(self) -> None:
        alarm = Alarm(
            type="checkpoint_failed",
            severity="warning",
            stage="code_generation",
            message="Generated code did not produce analysis.",
            context={"artifact": "analysis.json"},
            recommended_action="retry",
            retry_from="code_generation",
        )
        state = RunState(
            run_id="run-1",
            question="What happened to CPI?",
            current_stage=Stage.CODE_GENERATION,
            retry_count=2,
            artifacts={"plan": "plan.json"},
            alarms=[alarm],
        )

        data = state.to_dict()

        self.assertEqual(data["current_stage"], "code_generation")
        self.assertEqual(data["max_turns"], 5)
        self.assertEqual(data["alarms"][0]["retry_from"], "code_generation")

    def test_run_state_deserializes_alarms_to_alarm_objects(self) -> None:
        state = RunState.from_dict(
            {
                "run_id": "run-1",
                "question": "What happened to CPI?",
                "current_stage": "draft_answer",
                "retry_count": 1,
                "max_turns": 5,
                "artifacts": {"draft": "draft.json"},
                "alarms": [
                    {
                        "type": "answer_checkpoint_failed",
                        "severity": "warning",
                        "stage": "draft_answer",
                        "message": "Missing metric reference.",
                        "context": {"claim": "inflation cooled"},
                        "recommended_action": "retry",
                        "retry_from": "draft_answer",
                    }
                ],
            }
        )

        self.assertIs(state.current_stage, Stage.DRAFT_ANSWER)
        self.assertIsInstance(state.alarms[0], Alarm)
        self.assertEqual(state.alarms[0].retry_from, "draft_answer")


if __name__ == "__main__":
    unittest.main()
