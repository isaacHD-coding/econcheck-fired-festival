import unittest

from harness.alarms import Alarm


class AlarmTests(unittest.TestCase):
    def test_alarm_serializes_all_fields(self) -> None:
        alarm = Alarm(
            type="code_failure",
            severity="warning",
            stage="code_generation",
            message="The generated code failed.",
            context={"stderr": "NameError"},
            recommended_action="retry",
            retry_from="code_generation",
        )

        data = alarm.to_dict()

        self.assertEqual(
            data,
            {
                "type": "code_failure",
                "severity": "warning",
                "stage": "code_generation",
                "message": "The generated code failed.",
                "context": {"stderr": "NameError"},
                "recommended_action": "retry",
                "retry_from": "code_generation",
            },
        )

    def test_alarm_deserializes_all_fields(self) -> None:
        alarm = Alarm.from_dict(
            {
                "type": "unsupported_question",
                "severity": "critical",
                "stage": "input",
                "message": "Question is outside the FRED-answerable scope.",
                "context": {"question": "Who won the game?"},
                "recommended_action": "escalate",
                "retry_from": "",
            }
        )

        self.assertEqual(alarm.type, "unsupported_question")
        self.assertEqual(alarm.severity, "critical")
        self.assertEqual(alarm.stage, "input")
        self.assertEqual(alarm.message, "Question is outside the FRED-answerable scope.")
        self.assertEqual(alarm.context, {"question": "Who won the game?"})
        self.assertEqual(alarm.recommended_action, "escalate")
        self.assertEqual(alarm.retry_from, "")

    def test_alarm_defaults_are_safe_for_retry_routing(self) -> None:
        alarm = Alarm(
            type="checkpoint_failed",
            severity="warning",
            stage="data_discovery",
            message="Missing source provenance.",
        )

        self.assertEqual(alarm.context, {})
        self.assertEqual(alarm.recommended_action, "retry")
        self.assertEqual(alarm.retry_from, "")


if __name__ == "__main__":
    unittest.main()
