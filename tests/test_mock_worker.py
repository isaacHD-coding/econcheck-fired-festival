import unittest

from harness.state import RunState, Stage
from workers.artifacts import (
    AnalysisArtifact,
    CodeArtifact,
    DataSelectionArtifact,
    DraftArtifact,
    PlannerArtifact,
)
from workers.mock_worker import MockWorker


class MockWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = MockWorker()
        self.state = RunState(
            run_id="test-run",
            question="What has happened to CPI inflation over the last five years?",
            current_stage=Stage.PLANNING,
            retry_count=0,
        )

    def test_plan_returns_valid_planner_artifact(self) -> None:
        artifact = self.worker.plan(self.state.question, self.state)

        self.assertIsInstance(artifact, PlannerArtifact)
        self.assertEqual(PlannerArtifact.from_dict(artifact.to_dict()), artifact)

    def test_select_data_returns_valid_data_selection_artifact(self) -> None:
        plan = self.worker.plan(self.state.question, self.state)

        artifact = self.worker.select_data(
            plan,
            [
                {
                    "series_id": "CPIAUCSL",
                    "title": "Consumer Price Index for All Urban Consumers",
                    "frequency": "Monthly",
                    "units": "Index 1982-1984=100",
                }
            ],
        )

        self.assertIsInstance(artifact, DataSelectionArtifact)
        self.assertEqual(DataSelectionArtifact.from_dict(artifact.to_dict()), artifact)

    def test_write_code_returns_valid_code_artifact(self) -> None:
        plan = self.worker.plan(self.state.question, self.state)

        artifact = self.worker.write_code(
            plan,
            {"series_ids": ["CPIAUCSL"], "observations": {}, "metadata": {}},
        )

        self.assertIsInstance(artifact, CodeArtifact)
        self.assertEqual(CodeArtifact.from_dict(artifact.to_dict()), artifact)

    def test_draft_answer_returns_valid_draft_artifact(self) -> None:
        plan = self.worker.plan(self.state.question, self.state)
        analysis = AnalysisArtifact(
            tables=[],
            metrics=[
                {
                    "name": "cpi_change",
                    "value": 12.5,
                    "unit": "index points",
                    "source_series": ["CPIAUCSL"],
                }
            ],
            claims=[],
            charts=[],
            method_notes="Mock analysis artifact for worker contract tests.",
            warnings=[],
        )

        artifact = self.worker.draft_answer(plan, analysis)

        self.assertIsInstance(artifact, DraftArtifact)
        self.assertEqual(DraftArtifact.from_dict(artifact.to_dict()), artifact)


if __name__ == "__main__":
    unittest.main()
