from types import SimpleNamespace

from harness.checkpoints import (
    CHECKPOINT_REGISTRY,
    AnswerGroundingCheckpoint,
    ChartPromiseCheckpoint,
    CodeExecutionCheckpoint,
    DataCompletenessCheckpoint,
    FreshnessCheckpoint,
    InformationSufficiencyCheckpoint,
    MathSanityCheckpoint,
    OutputShapeCheckpoint,
    SourceProvenanceCheckpoint,
    SuccessCriteriaCheckpoint,
)
from workers.artifacts import AnalysisArtifact, DraftArtifact


def valid_analysis(metrics: list | None = None) -> AnalysisArtifact:
    return AnalysisArtifact(
        tables=[],
        metrics=metrics
        if metrics is not None
        else [
            {
                "name": "latest_cpi",
                "value": 310.326,
                "unit": "index",
                "source_series": ["CPIAUCSL"],
            }
        ],
        claims=[],
        charts=[],
        method_notes="Computed from FRED data.",
        warnings=[],
    )


def checkpoint_names(stage: str) -> set[str]:
    return {checkpoint.__class__.__name__ for checkpoint in CHECKPOINT_REGISTRY[stage]}


def test_checkpoint_registry_contains_required_checkpoints():
    assert checkpoint_names("data") == {
        "SourceProvenanceCheckpoint",
        "DataCompletenessCheckpoint",
        "FreshnessCheckpoint",
        "InformationSufficiencyCheckpoint",
    }
    assert checkpoint_names("code") == {
        "CodeExecutionCheckpoint",
        "OutputShapeCheckpoint",
        "MathSanityCheckpoint",
        "ChartPromiseCheckpoint",
    }
    assert checkpoint_names("answer") == {
        "AnswerGroundingCheckpoint",
        "SuccessCriteriaCheckpoint",
    }


def test_source_provenance_checkpoint_passes_when_every_metric_has_source_series():
    result = SourceProvenanceCheckpoint().evaluate(
        valid_analysis(
            metrics=[
                {"name": "metric_a", "source_series": ["CPIAUCSL"]},
                {"name": "metric_b", "source_series": []},
            ]
        )
    )

    assert result.passed is True
    assert result.alarm is None


def test_source_provenance_checkpoint_fails_metric_missing_source_series():
    result = SourceProvenanceCheckpoint().evaluate(
        valid_analysis(metrics=[{"name": "metric_a"}])
    )

    assert result.passed is False
    assert result.alarm is not None
    assert result.alarm.recommended_action == "retry"
    assert result.alarm.retry_from == "code_generation"


def test_stub_data_checkpoints_are_testable_and_pass_for_now():
    for checkpoint in (
        DataCompletenessCheckpoint(),
        FreshnessCheckpoint(),
        InformationSufficiencyCheckpoint(),
    ):
        result = checkpoint.evaluate(valid_analysis())

        assert result.passed is True
        assert result.alarm is None


def test_code_execution_checkpoint_passes_plain_analysis_artifact():
    result = CodeExecutionCheckpoint().evaluate(valid_analysis())

    assert result.passed is True
    assert result.alarm is None


def test_code_execution_checkpoint_fails_unsuccessful_execution_result():
    result = CodeExecutionCheckpoint().evaluate(
        {"succeeded": False, "execution_error": "NameError"}
    )

    assert result.passed is False
    assert result.alarm is not None
    assert result.alarm.recommended_action == "retry"
    assert result.alarm.retry_from == "code_generation"


def test_code_execution_checkpoint_fails_non_empty_execution_error_on_object():
    result = CodeExecutionCheckpoint().evaluate(
        SimpleNamespace(succeeded=True, execution_error="Traceback")
    )

    assert result.passed is False
    assert result.alarm is not None
    assert result.alarm.retry_from == "code_generation"


def test_output_shape_checkpoint_passes_when_all_required_fields_are_present_empty():
    result = OutputShapeCheckpoint().evaluate(
        {
            "tables": [],
            "metrics": [],
            "claims": [],
            "charts": [],
            "method_notes": "",
            "warnings": [],
        }
    )

    assert result.passed is True
    assert result.alarm is None


def test_output_shape_checkpoint_fails_missing_required_field():
    analysis = valid_analysis().to_dict()
    del analysis["warnings"]

    result = OutputShapeCheckpoint().evaluate(analysis)

    assert result.passed is False
    assert result.alarm is not None
    assert result.alarm.recommended_action == "retry"
    assert result.alarm.retry_from == "code_generation"


def test_output_shape_checkpoint_fails_malformed_object_without_throwing():
    result = OutputShapeCheckpoint().evaluate(SimpleNamespace(tables=[]))

    assert result.passed is False
    assert result.alarm is not None
    assert result.alarm.recommended_action == "retry"
    assert result.alarm.retry_from == "code_generation"


def test_stub_code_checkpoints_are_testable_and_pass_for_now():
    for checkpoint in (MathSanityCheckpoint(), ChartPromiseCheckpoint()):
        result = checkpoint.evaluate(valid_analysis())

        assert result.passed is True
        assert result.alarm is None


def test_answer_grounding_checkpoint_passes_when_referenced_metrics_exist():
    draft = DraftArtifact(
        answer="CPI rose.",
        referenced_metrics=["latest_cpi"],
        chart_paths=[],
    )

    result = AnswerGroundingCheckpoint().evaluate(draft, valid_analysis())

    assert result.passed is True
    assert result.alarm is None


def test_answer_grounding_checkpoint_fails_missing_metric_reference():
    draft = DraftArtifact(
        answer="CPI rose.",
        referenced_metrics=["missing_metric"],
        chart_paths=[],
    )

    result = AnswerGroundingCheckpoint().evaluate(draft, valid_analysis())

    assert result.passed is False
    assert result.alarm is not None
    assert result.alarm.recommended_action == "retry"
    assert result.alarm.retry_from == "draft_answer"


def test_success_criteria_checkpoint_is_testable_and_passes_for_now():
    result = SuccessCriteriaCheckpoint().evaluate(
        DraftArtifact(answer="", referenced_metrics=[], chart_paths=[]),
        valid_analysis(),
    )

    assert result.passed is True
    assert result.alarm is None
