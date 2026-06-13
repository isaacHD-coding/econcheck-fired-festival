import json
import tempfile
import unittest
from pathlib import Path

from harness.alarms import Alarm
from harness.persistence import (
    load_artifact,
    load_run_state,
    save_artifact,
    save_run_state,
)
from harness.state import RunState, Stage


class PersistenceTests(unittest.TestCase):
    def test_save_and_load_run_state_uses_state_json_under_run_directory(self) -> None:
        alarm = Alarm(
            type="data_failure",
            severity="warning",
            stage="data_discovery",
            message="No suitable series found.",
            context={"search": "CPI"},
            recommended_action="retry",
            retry_from="data_discovery",
        )
        state = RunState(
            run_id="run-1",
            question="What happened to CPI?",
            current_stage=Stage.DATA_DISCOVERY,
            retry_count=1,
            artifacts={"fred_search": "fred_search.json"},
            alarms=[alarm],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_run_state(state, tmpdir)
            loaded = load_run_state("run-1", tmpdir)

        self.assertEqual(path, Path(tmpdir) / "run-1" / "state.json")
        self.assertIs(loaded.current_stage, Stage.DATA_DISCOVERY)
        self.assertEqual(loaded.alarms[0].retry_from, "data_discovery")

    def test_save_run_state_writes_json_dictionary(self) -> None:
        state = RunState(
            run_id="run-1",
            question="What happened to CPI?",
            current_stage=Stage.INPUT,
            retry_count=0,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_run_state(state, tmpdir)
            data = json.loads(path.read_text())

        self.assertEqual(data["run_id"], "run-1")
        self.assertEqual(data["current_stage"], "input")

    def test_save_and_load_artifact_uses_json(self) -> None:
        artifact = {
            "question_type": "trend",
            "economic_concepts": ["inflation"],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_artifact("run-1", "plan", artifact, tmpdir)
            loaded = load_artifact("run-1", "plan", tmpdir)

        self.assertEqual(path, Path(tmpdir) / "run-1" / "plan.json")
        self.assertEqual(loaded, artifact)

    def test_save_artifact_preserves_json_suffix_when_provided(self) -> None:
        artifact = {"selected_series": [{"series_id": "CPIAUCSL"}]}

        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_artifact("run-1", "selected_data.json", artifact, tmpdir)

        self.assertEqual(path, Path(tmpdir) / "run-1" / "selected_data.json")


if __name__ == "__main__":
    unittest.main()
