import json
import unittest

from workers.artifacts import (
    AnalysisArtifact,
    ArtifactValidationError,
    CheckerArtifact,
    CodeArtifact,
    DataSelectionArtifact,
    DraftArtifact,
    PlannerArtifact,
)


def valid_plan_data() -> dict[str, object]:
    return {
        "question_type": "trend",
        "economic_concepts": ["inflation", "consumer prices"],
        "measurement_strategy": "Compare CPI levels and inflation rates over time.",
        "information_requirements": ["CPI time series", "recent observations"],
        "search_queries": ["consumer price index all urban consumers"],
        "required_outputs": ["summary metric", "trend table"],
        "success_criteria": ["Answer is grounded in CPI data"],
    }


class ArtifactTests(unittest.TestCase):
    def test_valid_planner_artifact_passes_validation(self) -> None:
        artifact = PlannerArtifact.from_dict(valid_plan_data())

        self.assertEqual(artifact.question_type, "trend")
        self.assertEqual(artifact.search_queries, ["consumer price index all urban consumers"])

    def test_missing_required_planner_field_fails_validation(self) -> None:
        data = valid_plan_data()
        del data["search_queries"]

        with self.assertRaisesRegex(ArtifactValidationError, "search_queries"):
            PlannerArtifact.from_dict(data)

    def test_empty_required_planner_field_fails_validation(self) -> None:
        data = valid_plan_data()
        data["measurement_strategy"] = ""

        with self.assertRaisesRegex(ArtifactValidationError, "measurement_strategy"):
            PlannerArtifact.from_dict(data)

    def test_invalid_planner_schema_fails_validation(self) -> None:
        data = valid_plan_data()
        data["economic_concepts"] = "inflation"

        with self.assertRaisesRegex(ArtifactValidationError, "economic_concepts"):
            PlannerArtifact.from_dict(data)

    def test_serialization_is_json_ready(self) -> None:
        artifact = PlannerArtifact.from_dict(valid_plan_data())

        serialized = artifact.to_dict()
        encoded = json.dumps(serialized)

        self.assertIn("question_type", encoded)

    def test_deserialization_round_trips_planner_artifact(self) -> None:
        data = valid_plan_data()

        artifact = PlannerArtifact.from_dict(data)

        self.assertEqual(artifact.to_dict(), data)

    def test_owned_artifacts_accept_valid_outer_schemas(self) -> None:
        DataSelectionArtifact(
            selected_series=[{"series_id": "CPIAUCSL", "reason": "Primary CPI series"}],
            rejected_series=[],
            justification="CPIAUCSL is the broad CPI measure.",
        )
        CodeArtifact(code="result = {'metrics': []}")
        AnalysisArtifact(
            tables=[],
            metrics=[{"unexpected": "inner schema is not validated here"}],
            claims=["outer shape only"],
            charts=[],
            method_notes="Computed from supplied data.",
            warnings=[],
        )
        DraftArtifact(
            answer="CPI inflation rose over the period.",
            referenced_metrics=["inflation_change"],
            chart_paths=[],
        )
        CheckerArtifact(
            passed=True,
            issues=[],
            retry_from="planning",
            explanation="Schema only.",
        )


if __name__ == "__main__":
    unittest.main()
