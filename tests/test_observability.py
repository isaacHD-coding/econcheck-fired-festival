import pytest


def test_run_question_returns_fixture_run_id() -> None:
    from harness.observability import run_question

    assert run_question("What has happened to CPI inflation over the last five years?") == (
        "sample_cpi_run"
    )


def test_fixture_loading_normalizes_sample_cpi_run() -> None:
    from harness.observability import load_run_artifacts

    run = load_run_artifacts("sample_cpi_run")

    assert run.run_id == "sample_cpi_run"
    assert run.source == "fixture"
    assert run.input["question"].startswith("What has happened to CPI inflation")
    assert [item["label"] for item in run.timeline] == [
        "Input Guardrails",
        "Planning",
        "Data Discovery",
        "Code Generation",
        "Draft Answer",
        "Release",
    ]
    assert run.planner["question_type"] == "trend"
    assert run.draft["answer"]


def test_runs_mode_is_future_seam_only() -> None:
    from harness.observability import load_run_artifacts

    with pytest.raises(NotImplementedError, match="future integration seam"):
        load_run_artifacts("run-1", mode="runs")


def test_guardrails_and_checkpoints_are_loaded_separately() -> None:
    from harness.observability import load_run_artifacts

    run = load_run_artifacts("sample_cpi_run")

    assert run.guardrails
    assert run.checkpoints
    assert run.guardrails is not run.checkpoints
    assert {item["kind"] for item in run.guardrails} == {"guardrail"}
    assert {item["kind"] for item in run.checkpoints} == {"checkpoint"}


def test_timeline_maps_each_stage_to_corresponding_artifact() -> None:
    from harness.observability import load_run_artifacts
    from harness.observability.view_models import artifact_for_stage

    run = load_run_artifacts("sample_cpi_run")

    assert artifact_for_stage(run, "input_guardrails") == run.guardrails
    assert artifact_for_stage(run, "planning") == run.planner
    assert artifact_for_stage(run, "data_discovery") == run.data_selection
    assert artifact_for_stage(run, "code_generation") == run.code
    assert artifact_for_stage(run, "draft_answer") == run.analysis
    assert artifact_for_stage(run, "release") == run.draft


def test_structured_planner_summary_prioritizes_required_fields() -> None:
    from harness.observability import load_run_artifacts
    from harness.observability.view_models import planner_summary

    run = load_run_artifacts("sample_cpi_run")
    summary = planner_summary(run.planner)

    assert summary["question_type"] == "trend"
    assert "inflation" in summary["economic_concepts"]
    assert "measurement_strategy" in summary
    assert "raw_json" not in summary


def test_structured_analysis_summary_prioritizes_metrics_claims_charts_warnings() -> None:
    from harness.observability import load_run_artifacts
    from harness.observability.view_models import analysis_summary

    run = load_run_artifacts("sample_cpi_run")
    summary = analysis_summary(run.analysis)

    assert summary["metrics"]
    assert summary["claims"]
    assert summary["charts"]
    assert "warnings" in summary
    assert "raw_json" not in summary


def test_status_item_label_supports_alarm_shape() -> None:
    from harness.observability.streamlit_ui import status_item_label

    status, name = status_item_label(
        {
            "type": "freshness_note",
            "severity": "info",
            "message": "Latest CPI observation depends on the release calendar.",
        }
    )

    assert status == "INFO"
    assert name == "freshness_note"
