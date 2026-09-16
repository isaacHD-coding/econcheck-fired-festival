import unittest

from harness.state import RunState, Stage
from workers.artifacts import (
    AnalysisArtifact,
    ChartBriefArtifact,
    CodeArtifact,
    DataArtifact,
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

    def test_design_chart_returns_single_series_brief_for_cpi(self) -> None:
        plan = self.worker.plan(self.state.question, self.state)
        brief = self.worker.design_chart(
            plan,
            DataArtifact(
                series_ids=["CPIAUCSL"],
                observations={"CPIAUCSL": []},
                metadata={"source": "FRED"},
            ),
        )

        self.assertIsInstance(brief, ChartBriefArtifact)
        self.assertEqual(brief.series_ids, ["CPIAUCSL"])
        self.assertEqual(brief.layout, "single")
        self.assertIn("levels", brief.transforms)

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

    def test_relationship_question_plans_cpi_and_gdp_without_inventing_series(self) -> None:
        question = (
            "What is the correlation (or anti correlation) between inflation "
            "and real GDP growth?"
        )
        plan = self.worker.plan(question, self.state)
        selection = self.worker.select_data(
            plan,
            [
                {
                    "series_id": "CPIAUCSL",
                    "title": "Consumer Price Index for All Urban Consumers",
                    "frequency": "Monthly",
                    "units": "Index 1982-1984=100",
                },
                {
                    "series_id": "GDPC1",
                    "title": "Real Gross Domestic Product",
                    "frequency": "Quarterly",
                    "units": "Billions of Chained 2017 Dollars",
                },
            ],
        )
        empty_selection = self.worker.select_data(
            plan,
            [
                {
                    "series_id": "UNRATE",
                    "title": "Unemployment Rate",
                    "frequency": "Monthly",
                    "units": "Percent",
                }
            ],
        )

        self.assertEqual(plan.question_type, "relationship")
        self.assertEqual(
            {item["series_id"] for item in selection.selected_series},
            {"CPIAUCSL", "GDPC1"},
        )
        self.assertEqual(empty_selection.selected_series, [])

    def test_cpi_pce_question_plans_and_selects_both_inflation_series(self) -> None:
        question = (
            "What is the difference between CPI and PCE inflation over the last 5 years?"
        )
        plan = self.worker.plan(question, self.state)
        selection = self.worker.select_data(
            plan,
            [
                {
                    "series_id": "CPIAUCSL",
                    "title": "Consumer Price Index for All Urban Consumers",
                    "frequency": "Monthly",
                    "units": "Index 1982-1984=100",
                },
                {
                    "series_id": "PCEPI",
                    "title": "Personal Consumption Expenditures Chain-type Price Index",
                    "frequency": "Monthly",
                    "units": "Index 2017=100",
                },
            ],
        )

        self.assertEqual(plan.question_type, "comparison")
        self.assertEqual(
            {item["series_id"] for item in selection.selected_series},
            {"CPIAUCSL", "PCEPI"},
        )

    def test_relationship_design_chart_covers_fetched_series(self) -> None:
        question = (
            "What is the correlation (or anti correlation) between inflation "
            "and real GDP growth?"
        )
        plan = self.worker.plan(question, self.state)
        brief = self.worker.design_chart(
            plan,
            DataArtifact(
                series_ids=["CPIAUCSL", "GDPC1"],
                observations={"CPIAUCSL": [], "GDPC1": []},
                metadata={"source": "FRED"},
            ),
        )

        self.assertEqual(set(brief.series_ids), {"CPIAUCSL", "GDPC1"})
        self.assertIn("growth", brief.transforms)
        self.assertEqual(brief.layout, "single")
        self.assertFalse(brief.y_starts_at_zero)
        self.assertIn("CPI growth", brief.title)
        self.assertIn("Real GDP growth", brief.title)
        self.assertNotIn("Do not place incompatible", brief.notes)


if __name__ == "__main__":
    unittest.main()
