from datetime import date

from types import SimpleNamespace

from harness.checkpoints import (
    CHECKPOINT_REGISTRY,
    AnswerGroundingCheckpoint,
    ChartBriefCheckpoint,
    ChartHonestyCheckpoint,
    ChartLabelCheckpoint,
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
from workers.artifacts import AnalysisArtifact, ChartBriefArtifact, DataArtifact, DraftArtifact


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
        charts=[{"type": "line", "title": "CPI", "data": [{"date": "2026-01-01", "value": 310.3}]}],
        method_notes="Computed from FRED data.",
        warnings=[],
    )


def valid_data(series_id: str = "CPIAUCSL", rows: int = 61) -> DataArtifact:
    observations = []
    today = date.today()
    start_year = today.year - 5
    start_month = today.month
    for index in range(rows):
        month_index = start_month - 1 + index
        year = start_year + month_index // 12
        month = month_index % 12 + 1
        observations.append(
            {
                "series_id": series_id,
                "date": f"{year:04d}-{month:02d}-01",
                "value": 260.0 + index,
            }
        )
    return DataArtifact(
        series_ids=[series_id],
        observations={series_id: observations},
        metadata={"source": "FRED"},
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
        "ChartHonestyCheckpoint",
        "ChartLabelCheckpoint",
        "ChartBriefCheckpoint",
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


def test_data_completeness_checkpoint_passes_enough_observations():
    result = DataCompletenessCheckpoint().evaluate(
        valid_data(),
        selected_series=[{"series_id": "CPIAUCSL", "frequency": "Monthly"}],
    )

    assert result.passed is True
    assert result.alarm is None


def test_data_completeness_checkpoint_fails_short_series():
    result = DataCompletenessCheckpoint().evaluate(
        valid_data(rows=10),
        selected_series=[{"series_id": "CPIAUCSL", "frequency": "Monthly"}],
    )

    assert result.passed is False
    assert result.alarm is not None
    assert result.alarm.retry_from == "data_discovery"


def test_freshness_checkpoint_fails_stale_observations():
    data = DataArtifact(
        series_ids=["CPIAUCSL"],
        observations={
            "CPIAUCSL": [
                {"series_id": "CPIAUCSL", "date": "2010-01-01", "value": 200.0}
            ]
        },
        metadata={"source": "FRED"},
    )

    result = FreshnessCheckpoint().evaluate(data, selected_ids=["CPIAUCSL"])

    assert result.passed is False
    assert result.alarm is not None
    assert result.alarm.retry_from == "data_discovery"


def test_information_sufficiency_requires_cpiaucsl_for_cpi_questions():
    result = InformationSufficiencyCheckpoint().evaluate(
        valid_data(series_id="UNRATE"),
        selected_ids=["UNRATE"],
        question="What has happened to CPI inflation over the last five years?",
    )

    assert result.passed is False
    assert result.alarm is not None


def test_information_sufficiency_requires_two_series_for_relationship_questions():
    result = InformationSufficiencyCheckpoint().evaluate(
        valid_data(),
        selected_ids=["CPIAUCSL"],
        question=(
            "What is the correlation (or anti correlation) between inflation "
            "and real GDP growth?"
        ),
    )

    assert result.passed is False
    assert result.alarm is not None


def test_information_sufficiency_requires_two_series_for_cpi_pce_questions():
    result = InformationSufficiencyCheckpoint().evaluate(
        valid_data(),
        selected_ids=["CPIAUCSL"],
        question="What is the difference between CPI and PCE inflation over the last 5 years?",
    )

    assert result.passed is False
    assert result.alarm is not None
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


def test_math_sanity_checkpoint_rejects_non_finite_metrics():
    analysis = valid_analysis(
        metrics=[
            {
                "name": "bad",
                "value": float("nan"),
                "unit": "percent",
                "source_series": ["CPIAUCSL"],
            }
        ]
    )

    result = MathSanityCheckpoint().evaluate(analysis)

    assert result.passed is False
    assert result.alarm is not None
    assert result.alarm.retry_from == "code_generation"


def test_chart_promise_checkpoint_fails_without_charts():
    analysis = valid_analysis()
    analysis.charts = []

    result = ChartPromiseCheckpoint().evaluate(analysis)

    assert result.passed is False
    assert result.alarm is not None
    assert result.alarm.retry_from == "code_generation"


def test_chart_honesty_checkpoint_fails_dwarf_shared_axis():
    analysis = valid_analysis()
    analysis.charts = [
        {
            "type": "line",
            "layout": "single",
            "y_field": ["CPIAUCSL", "GDPC1"],
            "data": [
                {"date": "2021-01-01", "CPIAUCSL": 260.0, "GDPC1": 19000.0},
                {"date": "2022-01-01", "CPIAUCSL": 280.0, "GDPC1": 21000.0},
            ],
        }
    ]

    result = ChartHonestyCheckpoint().evaluate(analysis)

    assert result.passed is False
    assert result.alarm is not None
    assert result.alarm.retry_from == "code_generation"


def test_chart_honesty_checkpoint_passes_growth_overlay():
    analysis = valid_analysis()
    analysis.charts = [
        {
            "type": "line",
            "layout": "single",
            "y_field": ["CPIAUCSL_growth", "GDPC1_growth"],
            "unit": "percent",
            "series_id": "CPIAUCSL,GDPC1",
            "data": [
                {"date": "2021-04-01", "CPIAUCSL_growth": 1.2, "GDPC1_growth": 0.4},
            ],
        }
    ]

    result = ChartHonestyCheckpoint().evaluate(analysis)

    assert result.passed is True


def test_chart_label_checkpoint_requires_units_and_series_ids():
    analysis = valid_analysis()
    analysis.charts = [
        {
            "type": "line",
            "y_field": ["CPIAUCSL_growth", "GDPC1_growth"],
            "data": [{"date": "2021-04-01", "CPIAUCSL_growth": 1.2, "GDPC1_growth": 0.4}],
        }
    ]

    result = ChartLabelCheckpoint().evaluate(analysis)

    assert result.passed is False
    assert result.alarm.retry_from == "code_generation"

    analysis.charts[0]["unit"] = "percent"
    analysis.charts[0]["series_ids"] = ["CPIAUCSL", "GDPC1"]
    result = ChartLabelCheckpoint().evaluate(analysis)
    assert result.passed is True


def test_chart_brief_checkpoint_requires_validated_multi_series_brief():
    data = DataArtifact(
        series_ids=["CPIAUCSL", "GDPC1"],
        observations={"CPIAUCSL": [], "GDPC1": []},
        metadata={"source": "FRED"},
    )
    missing = ChartBriefCheckpoint().evaluate(None, data, question="correlation of inflation and GDP")
    assert missing.passed is False
    assert missing.alarm.retry_from == "code_generation"

    invented = ChartBriefCheckpoint().evaluate(
        ChartBriefArtifact(
            claim="Comovement of inflation and made-up output.",
            series_ids=["CPIAUCSL", "FAKE123"],
            transforms=["growth"],
            layout="single",
            y_starts_at_zero=False,
            time_window_rationale="Overlap window.",
            annotations=[],
            title="Inflation vs fake series",
            x_label="date",
            y_label="percent",
            units="percent",
            notes="Would invent a series.",
            chart_type="line",
        ),
        data,
        question="correlation of inflation and GDP",
    )
    assert invented.passed is False

    valid = ChartBriefCheckpoint().evaluate(
        ChartBriefArtifact(
            claim="Growth in CPIAUCSL and GDPC1 is associated.",
            series_ids=["CPIAUCSL", "GDPC1"],
            transforms=["growth"],
            layout="single",
            y_starts_at_zero=False,
            time_window_rationale="Overlapping fetched window.",
            annotations=[],
            title="Period-over-period growth: CPI (CPIAUCSL) vs real GDP (GDPC1)",
            x_label="date",
            y_label="percent change",
            units="percent",
            notes="LOCF alignment; report overlap n.",
            chart_type="line",
        ),
        data,
        question="correlation of inflation and GDP",
    )
    assert valid.passed is True


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


def test_success_criteria_checkpoint_requires_grounded_answer():
    result = SuccessCriteriaCheckpoint().evaluate(
        DraftArtifact(answer="", referenced_metrics=[], chart_paths=[]),
        valid_analysis(),
        question="What has happened to CPI inflation over the last five years?",
    )

    assert result.passed is False
    assert result.alarm is not None


def test_success_criteria_checkpoint_passes_grounded_cpi_answer():
    result = SuccessCriteriaCheckpoint().evaluate(
        DraftArtifact(
            answer="CPI rose over five years.",
            referenced_metrics=["latest_cpi"],
            chart_paths=[],
        ),
        valid_analysis(),
        question="What has happened to CPI inflation over the last five years?",
    )

    assert result.passed is True
    assert result.alarm is None
