from __future__ import annotations

import pytest

from harness.state import RunState, Stage
from workers.artifacts import (
    AnalysisArtifact,
    CodeArtifact,
    DataArtifact,
    DataSelectionArtifact,
    DraftArtifact,
    PlannerArtifact,
)
from workers.base import Worker
from harness.tools.code_runner import run_analysis_code
from workers.openai_client import (
    OPENAI_PLAN_TIMEOUT_SECONDS,
    OpenAITimeoutError,
)
from workers.openai_worker import (
    OpenAIWorker,
    OpenAIWorkerError,
    OpenAIWorkerTimeoutError,
    SIMPLE_RETRY_WRITE_CODE_GUIDANCE,
    WRITE_CODE_GUIDANCE,
)


QUESTION = "What has happened to CPI inflation over the last five years?"


def test_openai_worker_conforms_to_worker_protocol() -> None:
    assert isinstance(OpenAIWorker(api_key="test-key"), Worker)


def test_openai_worker_methods_return_valid_artifacts(monkeypatch) -> None:
    responses = {
        "planner_artifact": {
            "question_type": "trend",
            "economic_concepts": ["inflation", "consumer prices"],
            "measurement_strategy": "Measure CPI index change and latest YoY CPI inflation.",
            "information_requirements": ["FRED CPI series", "recent CPI observations"],
            "search_queries": ["Consumer Price Index All Urban Consumers CPIAUCSL"],
            "required_outputs": ["five-year CPI change", "latest YoY inflation"],
            "success_criteria": ["Answer is grounded in CPIAUCSL metrics"],
        },
        "data_selection_artifact": {
            "selected_series": [{"series_id": "CPIAUCSL", "reason": "Primary CPI series"}],
            "rejected_series": [],
            "justification": "CPIAUCSL directly measures CPI for all urban consumers.",
        },
        "code_artifact": {
            "code": (
                "analysis_output = {"
                "'tables': [], 'metrics': [], 'claims': [], 'charts': [], "
                "'method_notes': 'computed from input_data', 'warnings': []}"
            )
        },
        "draft_artifact": {
            "answer": "CPI rose over the five-year window.",
            "referenced_metrics": ["cpi_five_year_change_percent"],
            "chart_paths": ["analysis.json#charts/0"],
        },
    }

    def fake_call_openai_json(*, schema_name, **kwargs):
        return responses[schema_name]

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    state = RunState("openai-worker", QUESTION, Stage.PLANNING, 0)
    plan = worker.plan(QUESTION, state)
    selection = worker.select_data(plan, [{"series_id": "CPIAUCSL", "title": "CPI"}])
    code = worker.write_code(plan, _data_artifact())
    draft = worker.draft_answer(plan, _analysis_artifact())

    assert isinstance(plan, PlannerArtifact)
    assert isinstance(selection, DataSelectionArtifact)
    assert isinstance(code, CodeArtifact)
    assert isinstance(draft, DraftArtifact)


def test_openai_worker_malformed_model_json_raises_clear_error(monkeypatch) -> None:
    def fake_call_openai_json(**kwargs):
        return {"question_type": "trend"}

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    state = RunState("openai-worker", QUESTION, Stage.PLANNING, 0)

    with pytest.raises(OpenAIWorkerError, match="plan response did not match"):
        worker.plan(QUESTION, state)


def test_openai_worker_passes_stage_specific_timeouts(monkeypatch) -> None:
    captured: dict[str, float] = {}
    responses = {
        "planner_artifact": {
            "question_type": "trend",
            "economic_concepts": ["inflation"],
            "measurement_strategy": "Measure CPI.",
            "information_requirements": ["FRED CPI series"],
            "search_queries": ["CPIAUCSL"],
            "required_outputs": ["five-year CPI change"],
            "success_criteria": ["Answer is grounded"],
        },
        "code_artifact": {
            "code": (
                "analysis_output = {"
                "'tables': [], 'metrics': [], 'claims': [], 'charts': [], "
                "'method_notes': 'computed from input_data', 'warnings': []}"
            )
        },
        "chart_brief_artifact": {
            "claim": "CPI rose.",
            "series_ids": ["CPIAUCSL"],
            "transforms": ["none"],
            "layout": "single",
            "y_starts_at_zero": False,
            "time_window_rationale": "Last five years.",
            "annotations": [],
            "title": "CPI",
            "x_label": "Date",
            "y_label": "Index",
            "units": "index",
            "notes": "CPIAUCSL",
            "chart_type": "line",
            "y_left_label": "",
            "y_right_label": "",
            "design_notes": "",
        },
    }

    def fake_call_openai_json(*, schema_name, timeout_seconds, **kwargs):
        captured[schema_name] = timeout_seconds
        return responses[schema_name]

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    state = RunState("openai-timeouts", QUESTION, Stage.PLANNING, 0)
    worker.plan(QUESTION, state)

    assert captured["planner_artifact"] == OPENAI_PLAN_TIMEOUT_SECONDS
    assert "chart_brief_artifact" not in captured
    assert "code_artifact" not in captured


def test_openai_worker_timeout_raises_friendly_error(monkeypatch) -> None:
    def fake_call_openai_json(**kwargs):
        raise OpenAITimeoutError(
            "planner_artifact",
            OPENAI_PLAN_TIMEOUT_SECONDS,
            stage_label="plan",
        )

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    with pytest.raises(OpenAIWorkerTimeoutError, match="Planning took longer than 30") as err:
        worker.plan(QUESTION, RunState("openai-timeout", QUESTION, Stage.PLANNING, 0))

    assert "did not match" not in str(err.value)
    assert "OpenAIWorkerError" not in str(err.value)
    assert err.value.timeout_seconds == OPENAI_PLAN_TIMEOUT_SECONDS
    assert err.value.stage_label == "plan"


def test_openai_worker_recovers_canonical_cpi_selection_after_empty_model_choice(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_call_openai_json(*, schema_name, **kwargs):
        calls.append(schema_name)
        return {
            "selected_series": [],
            "rejected_series": [],
            "justification": "Model declined to select a series.",
        }

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = QUESTION
    selection = worker.select_data(
        _planner_artifact(),
        [
            {
                "series_id": "CPIAUCSL",
                "title": (
                    "Consumer Price Index for All Urban Consumers: "
                    "All Items in U.S. City Average"
                ),
                "frequency": "Monthly",
                "units": "Index 1982-1984=100",
                "observation_start": "1947-01-01",
                "observation_end": "2026-05-01",
            }
        ],
    )

    assert calls == ["data_selection_artifact"]
    assert selection.selected_series[0]["series_id"] == "CPIAUCSL"
    assert "canonical CPI" in selection.justification


def test_openai_worker_uses_executable_canonical_cpi_template_without_model_call(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_call_openai_json(*, schema_name, **kwargs):
        calls.append(schema_name)
        raise AssertionError("canonical CPI codegen must not call OpenAI")

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = QUESTION
    code = worker.write_code(
        _planner_artifact(),
        _canonical_cpi_data_artifact(),
    )
    analysis = run_analysis_code(code, _canonical_cpi_data_artifact())

    assert calls == []
    assert analysis.tables
    assert analysis.metrics
    assert analysis.charts
    assert {metric["name"] for metric in analysis.metrics} >= {
        "cpi_five_year_change_percent",
        "latest_yoy_inflation_percent",
        "latest_cpi_index",
    }


def test_openai_worker_uses_grounded_canonical_cpi_draft_without_model_call(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_call_openai_json(*, schema_name, **kwargs):
        calls.append(schema_name)
        raise AssertionError("canonical CPI draft must not call OpenAI")

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = QUESTION
    draft = worker.draft_answer(
        _planner_artifact(),
        _canonical_cpi_analysis_artifact(),
    )

    assert calls == []
    assert "CPI" in draft.answer
    assert set(draft.referenced_metrics) >= {
        "cpi_five_year_change_percent",
        "latest_yoy_inflation_percent",
        "latest_cpi_index",
    }
    assert draft.chart_paths == ["analysis.json#charts/0"]


ISAAC_QUESTION = (
    "What is the correlation (or anti correlation) between inflation and real GDP growth?"
)


def test_openai_worker_does_not_recover_cpi_only_selection_for_correlation_question(
    monkeypatch,
) -> None:
    def fake_call_openai_json(*, schema_name, **kwargs):
        return {
            "selected_series": [],
            "rejected_series": [],
            "justification": "Model declined to select a series.",
        }

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = ISAAC_QUESTION
    selection = worker.select_data(
        _relationship_plan(),
        [_cpi_search_result()],
    )

    assert selection.selected_series == []


def test_openai_worker_adds_search_backed_gdp_when_model_selects_only_cpi(
    monkeypatch,
) -> None:
    def fake_call_openai_json(*, schema_name, **kwargs):
        result = _cpi_search_result()
        result["reason"] = "Inflation"
        return {
            "selected_series": [result],
            "rejected_series": [],
            "justification": "Model selected CPIAUCSL only.",
        }

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = ISAAC_QUESTION
    selection = worker.select_data(
        _relationship_plan(),
        [_cpi_search_result(), _gdp_search_result()],
    )

    assert {item["series_id"] for item in selection.selected_series} == {
        "CPIAUCSL",
        "GDPC1",
    }


def test_openai_worker_uses_relationship_template_instead_of_canonical_cpi_code(
    monkeypatch,
) -> None:
    def fake_call_openai_json(*, schema_name, **kwargs):
        raise AssertionError(f"unexpected OpenAI call for {schema_name}")

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = ISAAC_QUESTION
    code = worker.write_code(_relationship_plan(), _cpi_and_gdp_data())

    assert "Expected at least 48 CPI observations" not in code.code
    assert "growth_correlation" in code.code
    assert "pearson" in code.code


def test_openai_worker_skips_openai_write_code_for_multiseries_data(
    monkeypatch,
) -> None:
    def fake_call_openai_json(*, schema_name, **kwargs):
        raise AssertionError(f"unexpected OpenAI call for {schema_name}")

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = ISAAC_QUESTION
    code = worker.write_code(_relationship_plan(), _cpi_and_gdp_data())

    assert "pearson" in code.code
    assert "GDPC1" in code.code
    assert "Expected at least 48 CPI observations" not in code.code


def test_openai_worker_does_not_release_canned_cpi_draft_for_correlation_question(
    monkeypatch,
) -> None:
    def fake_call_openai_json(*, schema_name, **kwargs):
        return {
            "answer": (
                "Over the last five years, CPI inflation has left the CPI index "
                "materially higher. The CPIAUCSL index increased by 21.99%."
            ),
            "referenced_metrics": [
                "cpi_five_year_change_percent",
                "latest_yoy_inflation_percent",
                "latest_cpi_index",
            ],
            "chart_paths": ["analysis.json#charts/0"],
        }

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = ISAAC_QUESTION
    analysis = AnalysisArtifact(
        tables=[],
        metrics=[
            {
                "name": "growth_correlation",
                "value": -0.37,
                "unit": "correlation",
                "source_series": ["CPIAUCSL", "GDPC1"],
            },
            {
                "name": "overlap_periods",
                "value": 19,
                "unit": "periods",
                "source_series": ["CPIAUCSL", "GDPC1"],
            },
        ],
        claims=[],
        charts=[{"type": "line", "data": []}],
        method_notes="Aligned CPIAUCSL and GDPC1.",
        warnings=[],
    )

    draft = worker.draft_answer(_relationship_plan(), analysis)

    assert "materially higher" not in draft.answer
    assert "correlation" in draft.answer.lower()
    assert "GDPC1" in draft.answer
    assert "CPI all items" in draft.answer or "inflation" in draft.answer.lower()
    assert "real GDP" in draft.answer
    assert "contemporaneous association" not in draft.answer.lower()
    assert "growth_correlation" in draft.referenced_metrics


def test_openai_worker_uses_relationship_draft_template_without_openai(
    monkeypatch,
) -> None:
    def fake_call_openai_json(*, schema_name, **kwargs):
        raise AssertionError(f"unexpected OpenAI call for {schema_name}")

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = ISAAC_QUESTION
    analysis = AnalysisArtifact(
        tables=[],
        metrics=[
            {
                "name": "growth_correlation",
                "value": -0.37,
                "unit": "correlation",
                "source_series": ["CPIAUCSL", "GDPC1"],
            }
        ],
        claims=[],
        charts=[{"type": "line", "data": []}],
        method_notes="model",
        warnings=[],
    )

    draft = worker.draft_answer(_relationship_plan(), analysis)

    assert "correlation" in draft.answer.lower()
    assert "real GDP" in draft.answer
    assert "materially higher" not in draft.answer


def test_openai_worker_rewrites_jargony_correlation_draft(monkeypatch) -> None:
    def fake_call_openai_json(*, schema_name, **kwargs):
        return {
            "answer": (
                "Over the overlapping FRED window, period-over-period growth in "
                "CPIAUCSL and GDPC1 is anti-correlated (negative contemporaneous "
                "association). This does not by itself identify lead-lag."
            ),
            "referenced_metrics": ["growth_correlation"],
            "chart_paths": ["analysis.json#charts/0"],
        }

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = ISAAC_QUESTION
    analysis = AnalysisArtifact(
        tables=[],
        metrics=[
            {
                "name": "growth_correlation",
                "value": -0.46,
                "unit": "correlation",
                "source_series": ["CPIAUCSL", "GDPC1"],
            },
            {
                "name": "overlap_periods",
                "value": 18,
                "unit": "periods",
                "source_series": ["CPIAUCSL", "GDPC1"],
            },
        ],
        claims=[],
        charts=[{"type": "line", "data": []}],
        method_notes="model",
        warnings=[],
    )

    draft = worker.draft_answer(_relationship_plan(), analysis)

    assert "contemporaneous association" not in draft.answer.lower()
    assert "inflation" in draft.answer.lower()
    assert "real GDP" in draft.answer
    assert "CPI all items" in draft.answer


def test_openai_worker_design_chart_does_not_call_openai(monkeypatch) -> None:
    def fake_call_openai_json(*, schema_name, **kwargs):
        raise AssertionError(f"unexpected OpenAI call for {schema_name}")

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = ISAAC_QUESTION
    brief = worker.design_chart(_relationship_plan(), _cpi_and_gdp_data())

    assert set(brief.series_ids) == {"CPIAUCSL", "GDPC1"}
    assert "growth" in brief.transforms


def test_openai_worker_write_code_attaches_chart_brief_without_openai(
    monkeypatch,
) -> None:
    def fake_call_openai_json(*, schema_name, **kwargs):
        raise AssertionError(f"unexpected OpenAI call for {schema_name}")

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = ISAAC_QUESTION
    data = _cpi_and_gdp_data()
    brief = worker.design_chart(_relationship_plan(), data)
    code = worker.write_code(_relationship_plan(), data, chart_brief=brief)

    assert "growth_correlation" in code.code
    assert data.metadata["chart_brief"]["series_ids"] == brief.series_ids
    assert "growth" in data.metadata["chart_brief"]["transforms"]


def test_relationship_analysis_code_runs_for_cpi_and_gdp() -> None:
    from workers.analysis_templates import relationship_analysis_code

    analysis = run_analysis_code(
        CodeArtifact(code=relationship_analysis_code()),
        _cpi_and_gdp_data(),
    )

    metric_names = {metric["name"] for metric in analysis.metrics}
    assert "growth_correlation" in metric_names
    source_series = {
        series_id
        for metric in analysis.metrics
        for series_id in metric.get("source_series", [])
    }
    assert source_series >= {"CPIAUCSL", "GDPC1"}
    assert analysis.charts
    primary = analysis.charts[0]
    from harness.charts import normalize_chart, would_dwarf_a_series, y_fields

    normalized = normalize_chart(primary)
    assert would_dwarf_a_series(normalized) is False
    assert any("growth" in field for field in y_fields(normalized)) or normalized.get("layout") == "dual_axis"


def test_comparison_analysis_code_runs_for_cpi_and_pce() -> None:
    from workers.analysis_templates import comparison_analysis_code

    analysis = run_analysis_code(
        CodeArtifact(code=comparison_analysis_code()),
        _cpi_and_pce_data(),
    )

    metric_names = {metric["name"] for metric in analysis.metrics}
    assert "latest_inflation_gap_percent" in metric_names
    assert {metric["name"] for metric in analysis.metrics if metric.get("source_series")}
    source_series = {
        series_id
        for metric in analysis.metrics
        for series_id in (metric.get("source_series") or [])
    }
    assert source_series >= {"CPIAUCSL", "PCEPI"}
    assert "calendar month minus 12" in analysis.method_notes
    assert "positional" in analysis.method_notes
    assert "average_yoy_gap_percent" in metric_names
    assert "five_year_average_gap_percent" not in metric_names
    if int(next(m["value"] for m in analysis.metrics if m["name"] == "overlap_periods")) < 60:
        assert "not a five-year average" in analysis.method_notes


def test_comparison_draft_does_not_call_short_window_a_five_year_average() -> None:
    from workers.analysis_templates import comparison_draft

    analysis = AnalysisArtifact(
        tables=[],
        metrics=[
            {
                "name": "latest_left_yoy_percent",
                "value": 3.1,
                "unit": "percent",
                "source_series": ["CPIAUCSL"],
            },
            {
                "name": "latest_right_yoy_percent",
                "value": 2.8,
                "unit": "percent",
                "source_series": ["PCEPI"],
            },
            {
                "name": "latest_inflation_gap_percent",
                "value": 0.3,
                "unit": "percentage points",
                "source_series": ["CPIAUCSL", "PCEPI"],
            },
            {
                "name": "average_yoy_gap_percent",
                "value": 0.4,
                "unit": "percentage points",
                "source_series": ["CPIAUCSL", "PCEPI"],
            },
            {
                "name": "overlap_periods",
                "value": 46,
                "unit": "periods",
                "source_series": ["CPIAUCSL", "PCEPI"],
            },
        ],
        claims=[],
        charts=[
            {
                "type": "line",
                "data": [
                    {"date": "2022-09-01", "CPIAUCSL_yoy": 3.0, "PCEPI_yoy": 2.6},
                    {"date": "2026-07-01", "CPIAUCSL_yoy": 3.1, "PCEPI_yoy": 2.8},
                ],
            }
        ],
        method_notes="calendar month minus 12",
        warnings=[],
    )

    draft = comparison_draft(analysis)
    lowered = draft.answer.lower()
    assert "last five years" not in lowered
    assert "2022-09" in draft.answer
    assert "2026-07" in draft.answer
    assert "46" in draft.answer
    assert "not a five-year average" in lowered
    assert "basket" in lowered
    assert "weight" in lowered
    assert "formula" in lowered or "substitution" in lowered


def test_comparison_template_trims_yoy_window_to_requested_five_years() -> None:
    from workers.analysis_templates import comparison_analysis_code, comparison_draft

    data = _cpi_and_pce_long_history()
    analysis = run_analysis_code(
        CodeArtifact(code=comparison_analysis_code()),
        data,
    )

    window, expected_gaps, full_gaps = _expected_calendar_yoy_window(data, months=60)
    chart_dates = [str(row["date"])[:7] for row in analysis.charts[0]["data"]]
    overlap = next(m["value"] for m in analysis.metrics if m["name"] == "overlap_periods")
    avg_gap = next(m["value"] for m in analysis.metrics if m["name"] == "average_yoy_gap_percent")

    assert len(full_gaps) > 60
    assert overlap == 60
    assert len(chart_dates) == 60
    assert chart_dates[0] == window[0]
    assert chart_dates[-1] == window[-1]
    assert chart_dates[-1] == "2026-07"
    assert abs(float(avg_gap) - (sum(expected_gaps) / len(expected_gaps))) < 0.02
    assert abs((sum(full_gaps) / len(full_gaps)) - float(avg_gap)) > 0.01
    assert "trimmed" in analysis.method_notes.lower()
    assert "last five years" in analysis.method_notes.lower()

    draft = comparison_draft(analysis)
    lowered = draft.answer.lower()
    assert "last five years" in lowered
    assert "60" in draft.answer
    assert window[0] in draft.answer
    assert "2026-07" in draft.answer
    assert "basket" in lowered
    assert "weight" in lowered


def test_comparison_template_uses_calendar_yoy_when_a_month_is_missing() -> None:
    from workers.analysis_templates import comparison_analysis_code

    analysis = run_analysis_code(
        CodeArtifact(code=comparison_analysis_code()),
        _cpi_and_pce_data_with_missing_month(),
    )

    chart = analysis.charts[0]
    by_date = {row["date"][:7]: row for row in chart["data"]}
    assert "2025-11" in by_date
    assert "2025-10" not in by_date
    assert "2026-08" not in by_date
    cpi_nov = by_date["2025-11"]["CPIAUCSL_yoy"]
    calendar_yoy = ((159.0 / 147.0) - 1.0) * 100.0
    positional_yoy = ((159.0 / 146.0) - 1.0) * 100.0
    assert abs(cpi_nov - calendar_yoy) < 0.02
    assert abs(cpi_nov - positional_yoy) > 0.5
    table = analysis.tables[0]["rows"][0]
    assert table["latest_common_raw_month"] == "2026-07"
    assert analysis.charts[0]["data"][-1]["date"].startswith("2026-07")


CPI_PCE_QUESTION = (
    "What is the difference between CPI and PCE inflation over the last 5 years?"
)


def test_openai_worker_adds_search_backed_pce_when_model_selects_only_cpi(
    monkeypatch,
) -> None:
    def fake_call_openai_json(*, schema_name, **kwargs):
        result = _cpi_search_result()
        result["reason"] = "Inflation"
        return {
            "selected_series": [result],
            "rejected_series": [],
            "justification": "Model selected CPIAUCSL only.",
        }

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = CPI_PCE_QUESTION
    selection = worker.select_data(
        _comparison_plan(),
        [_cpi_search_result(), _pce_search_result()],
    )

    assert {item["series_id"] for item in selection.selected_series} == {
        "CPIAUCSL",
        "PCEPI",
    }


def test_openai_worker_uses_comparison_template_without_openai_write_code(
    monkeypatch,
) -> None:
    def fake_call_openai_json(*, schema_name, **kwargs):
        raise AssertionError(f"unexpected OpenAI call for {schema_name}")

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = CPI_PCE_QUESTION
    code = worker.write_code(_comparison_plan(), _cpi_and_pce_data())

    assert "latest_inflation_gap_percent" in code.code
    assert "PCEPI" in code.code
    assert "pearson" not in code.code


def test_write_code_guidance_keeps_generated_scripts_short() -> None:
    lowered = WRITE_CODE_GUIDANCE.lower()
    assert "80-120" in WRITE_CODE_GUIDANCE
    assert "chart_brief" in lowered
    assert "design_notes" in lowered
    assert "year-over-year" in lowered
    assert "inflation gap" in lowered
    assert "missing-month" in lowered
    assert "pearson" in lowered
    assert "general-purpose statistics library" in lowered
    assert "source_series" in lowered
    assert "metric['value']" in WRITE_CODE_GUIDANCE or "value: number" in lowered
    assert "charts[].series" in WRITE_CODE_GUIDANCE
    assert "latest_inflation_gap_percent" in WRITE_CODE_GUIDANCE
    assert "calendar" in lowered
    assert "positional" in lowered
    assert "inner-join" in lowered or "inner join" in lowered
    assert "60 months" in lowered
    assert "filtered window" in lowered or "requested window" in lowered
    assert "adaptive chart design" not in lowered
    assert "correlation is acceptable" not in lowered


def test_openai_write_code_openai_path_uses_concise_guidance(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_call_openai_json(*, schema_name, instructions, input_payload, **kwargs):
        captured["schema_name"] = schema_name
        captured["instructions"] = instructions
        captured["payload"] = input_payload
        return {
            "code": (
                "analysis_output = {"
                "'tables': [], 'metrics': [], 'claims': [], 'charts': [], "
                "'method_notes': 'computed from input_data', 'warnings': []}"
            )
        }

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = "How has the unemployment rate changed over the last five years?"
    code = worker.write_code(_unemployment_plan(), _unemployment_data())

    assert captured["schema_name"] == "code_artifact"
    instructions = str(captured["instructions"])
    assert WRITE_CODE_GUIDANCE in instructions
    assert "80-120" in instructions
    assert "Adaptive chart design" not in instructions
    assert "correlation is acceptable" not in instructions
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["codegen_constraints"]["max_lines"] == 120
    assert payload["codegen_constraints"]["price_index_comparison"] == (
        "yoy_percent_and_gap_only"
    )
    assert "metrics_schema" in payload["codegen_constraints"]
    assert "charts_schema" in payload["codegen_constraints"]
    assert isinstance(code, CodeArtifact)


def test_openai_write_code_retry_uses_schema_simplify_prompt(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_call_openai_json(*, schema_name, instructions, input_payload, **kwargs):
        captured["instructions"] = instructions
        captured["payload"] = input_payload
        return {
            "code": (
                "analysis_output = {"
                "'tables': [], 'metrics': [], 'claims': [], 'charts': [], "
                "'method_notes': 'retry', 'warnings': []}"
            )
        }

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = "How has the unemployment rate changed over the last five years?"
    data = _unemployment_data()
    data.metadata["codegen_retry"] = {
        "failed_checks": ["MathSanityCheckpoint", "ChartPromiseCheckpoint"],
        "instruction": "Previous analysis_output failed MathSanity and/or ChartPromise.",
    }
    worker.write_code(_unemployment_plan(), data)

    instructions = str(captured["instructions"])
    assert SIMPLE_RETRY_WRITE_CODE_GUIDANCE in instructions
    assert "schema X" in instructions or "y_field" in instructions
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["codegen_retry"]["failed_checks"] == [
        "MathSanityCheckpoint",
        "ChartPromiseCheckpoint",
    ]


def test_cpi_pce_write_code_path_keeps_concise_codegen_contract(monkeypatch) -> None:
    def fake_call_openai_json(*, schema_name, **kwargs):
        raise AssertionError(f"unexpected OpenAI call for {schema_name}")

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = CPI_PCE_QUESTION
    code = worker.write_code(_comparison_plan(), _cpi_and_pce_data())

    assert "80-120" in WRITE_CODE_GUIDANCE
    assert "CPIAUCSL vs PCEPI" in WRITE_CODE_GUIDANCE
    assert "latest_inflation_gap_percent" in code.code
    assert "pearson" not in code.code
    from harness.checkpoints.code import CodeSimplicityCheckpoint

    assert CodeSimplicityCheckpoint().evaluate(code).passed is True


def _comparison_plan() -> PlannerArtifact:
    return PlannerArtifact(
        question_type="comparison",
        economic_concepts=["CPI inflation", "PCE inflation"],
        measurement_strategy="Compare CPIAUCSL and PCEPI year-over-year inflation.",
        information_requirements=["CPIAUCSL", "PCEPI"],
        search_queries=["CPIAUCSL", "PCEPI"],
        required_outputs=["inflation gap"],
        success_criteria=["Report the CPI-PCE inflation difference"],
    )


def _unemployment_plan() -> PlannerArtifact:
    return PlannerArtifact(
        question_type="trend",
        economic_concepts=["unemployment"],
        measurement_strategy="Measure the change in UNRATE over five years.",
        information_requirements=["UNRATE"],
        search_queries=["UNRATE unemployment rate"],
        required_outputs=["five-year unemployment change"],
        success_criteria=["Answer cites UNRATE"],
    )


def _unemployment_data() -> DataArtifact:
    rows = [
        {"series_id": "UNRATE", "date": "2021-01-01", "value": 6.3},
        {"series_id": "UNRATE", "date": "2026-01-01", "value": 4.1},
    ]
    return DataArtifact(
        series_ids=["UNRATE"],
        observations={"UNRATE": rows},
        metadata={"source": "FRED"},
    )


def _relationship_plan() -> PlannerArtifact:
    return PlannerArtifact(
        question_type="relationship",
        economic_concepts=["inflation", "real GDP growth", "correlation"],
        measurement_strategy="Correlate CPIAUCSL and GDPC1 growth rates.",
        information_requirements=["CPIAUCSL", "GDPC1"],
        search_queries=["CPIAUCSL", "Real GDP GDPC1"],
        required_outputs=["correlation"],
        success_criteria=["Report the inflation/GDP correlation"],
    )


def _cpi_search_result() -> dict:
    return {
        "series_id": "CPIAUCSL",
        "title": "Consumer Price Index for All Urban Consumers: All Items",
        "frequency": "Monthly",
        "units": "Index 1982-1984=100",
        "observation_start": "1947-01-01",
        "observation_end": "2026-05-01",
        "reason": "",
    }


def _gdp_search_result() -> dict:
    return {
        "series_id": "GDPC1",
        "title": "Real Gross Domestic Product",
        "frequency": "Quarterly",
        "units": "Billions of Chained 2017 Dollars",
        "observation_start": "1947-01-01",
        "observation_end": "2026-04-01",
        "reason": "",
    }


def _pce_search_result() -> dict:
    return {
        "series_id": "PCEPI",
        "title": "Personal Consumption Expenditures: Chain-type Price Index",
        "frequency": "Monthly",
        "units": "Index 2017=100",
        "observation_start": "1959-01-01",
        "observation_end": "2026-05-01",
        "reason": "",
    }


def _cpi_and_pce_data() -> DataArtifact:
    cpi_rows = []
    pce_rows = []
    cpi_value = 260.0
    pce_value = 100.0
    for year in range(2021, 2027):
        for month in range(1, 13):
            if year == 2026 and month > 4:
                break
            cpi_rows.append(
                {
                    "series_id": "CPIAUCSL",
                    "date": f"{year}-{month:02d}-01",
                    "value": round(cpi_value, 3),
                }
            )
            pce_rows.append(
                {
                    "series_id": "PCEPI",
                    "date": f"{year}-{month:02d}-01",
                    "value": round(pce_value, 3),
                }
            )
            cpi_value += 0.8
            pce_value += 0.4
    return DataArtifact(
        series_ids=["CPIAUCSL", "PCEPI"],
        observations={"CPIAUCSL": cpi_rows, "PCEPI": pce_rows},
        metadata={"source": "FRED"},
    )


def _cpi_and_pce_long_history() -> DataArtifact:
    """83 monthly levels (2019-09..2026-07) so YoY overlap exceeds 60 months."""

    cpi_rows = []
    pce_rows = []
    year, month = 2019, 9
    for index in range(83):
        date = f"{year:04d}-{month:02d}-01"
        extra = 30.0 if year < 2021 else 0.0
        cpi_rows.append(
            {
                "series_id": "CPIAUCSL",
                "date": date,
                "value": round(200.0 + index + extra, 3),
            }
        )
        pce_rows.append(
            {
                "series_id": "PCEPI",
                "date": date,
                "value": round(100.0 + index * 0.5, 3),
            }
        )
        month += 1
        if month > 12:
            month = 1
            year += 1
    return DataArtifact(
        series_ids=["CPIAUCSL", "PCEPI"],
        observations={"CPIAUCSL": cpi_rows, "PCEPI": pce_rows},
        metadata={
            "source": "FRED",
            "requested_window_years": 5,
            "requested_yoy_months": 60,
        },
    )


def _expected_calendar_yoy_window(
    data: DataArtifact, months: int = 60
) -> tuple[list[str], list[float], list[float]]:
    left = {row["date"][:7]: float(row["value"]) for row in data.observations["CPIAUCSL"]}
    right = {row["date"][:7]: float(row["value"]) for row in data.observations["PCEPI"]}

    def yoy(levels: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for key, value in levels.items():
            prior_key = f"{int(key[:4]) - 1:04d}-{key[5:7]}"
            prior = levels.get(prior_key)
            if prior:
                out[key] = ((value / prior) - 1.0) * 100.0
        return out

    left_yoy = yoy(left)
    right_yoy = yoy(right)
    common = sorted(set(left_yoy) & set(right_yoy))
    full_gaps = [left_yoy[key] - right_yoy[key] for key in common]
    window = common[-months:]
    gaps = [left_yoy[key] - right_yoy[key] for key in window]
    return window, gaps, full_gaps


def _cpi_and_pce_data_with_missing_month() -> DataArtifact:
    cpi_rows = []
    pce_rows = []
    for year in range(2021, 2027):
        for month in range(1, 13):
            if year == 2026 and month > 8:
                break
            date = f"{year}-{month:02d}-01"
            cpi_value = 100.0 + (year - 2021) * 12 + month
            pce_value = 50.0 + (year - 2021) * 12 + month
            if year == 2025 and month == 10:
                pce_rows.append({"series_id": "PCEPI", "date": date, "value": pce_value})
                continue
            if year == 2026 and month == 8:
                cpi_rows.append({"series_id": "CPIAUCSL", "date": date, "value": cpi_value})
                continue
            if year == 2026 and month > 7:
                continue
            cpi_rows.append({"series_id": "CPIAUCSL", "date": date, "value": cpi_value})
            pce_rows.append({"series_id": "PCEPI", "date": date, "value": pce_value})
    return DataArtifact(
        series_ids=["CPIAUCSL", "PCEPI"],
        observations={"CPIAUCSL": cpi_rows, "PCEPI": pce_rows},
        metadata={"source": "FRED"},
    )


def _cpi_and_gdp_data() -> DataArtifact:
    cpi_rows = []
    gdp_rows = []
    value = 260.0
    gdp_value = 19000.0
    for year in range(2021, 2027):
        for month in range(1, 13):
            if year == 2026 and month > 4:
                break
            cpi_rows.append(
                {
                    "series_id": "CPIAUCSL",
                    "date": f"{year}-{month:02d}-01",
                    "value": round(value, 3),
                }
            )
            value += 0.8
            if month in {1, 4, 7, 10}:
                gdp_rows.append(
                    {
                        "series_id": "GDPC1",
                        "date": f"{year}-{month:02d}-01",
                        "value": round(gdp_value, 3),
                    }
                )
                gdp_value += 80.0
    return DataArtifact(
        series_ids=["CPIAUCSL", "GDPC1"],
        observations={"CPIAUCSL": cpi_rows, "GDPC1": gdp_rows},
        metadata={"source": "FRED"},
    )


def _data_artifact() -> DataArtifact:
    return DataArtifact(
        series_ids=["CPIAUCSL"],
        observations={
            "CPIAUCSL": [
                {"series_id": "CPIAUCSL", "date": "2025-01-01", "value": 310.0},
                {"series_id": "CPIAUCSL", "date": "2026-01-01", "value": 318.0},
            ]
        },
        metadata={"source": "FRED"},
    )


def _planner_artifact() -> PlannerArtifact:
    return PlannerArtifact(
        question_type="trend",
        economic_concepts=["inflation", "consumer prices"],
        measurement_strategy="Compute CPI index change and latest YoY inflation.",
        information_requirements=["FRED CPI series", "monthly observations"],
        search_queries=["FRED CPIAUCSL Consumer Price Index"],
        required_outputs=["five-year change", "latest YoY inflation"],
        success_criteria=["Answer cites CPI metrics"],
    )


def _canonical_cpi_data_artifact() -> DataArtifact:
    rows = []
    for year in range(2021, 2027):
        for month in range(1, 13):
            if year == 2026 and month > 1:
                break
            rows.append(
                {
                    "series_id": "CPIAUCSL",
                    "date": f"{year}-{month:02d}-01",
                    "value": 260.0 + len(rows),
                }
            )

    return DataArtifact(
        series_ids=["CPIAUCSL"],
        observations={"CPIAUCSL": rows},
        metadata={"source": "FRED"},
    )


def _analysis_artifact() -> AnalysisArtifact:
    return AnalysisArtifact(
        tables=[],
        metrics=[
            {
                "name": "cpi_five_year_change_percent",
                "value": 20.0,
                "unit": "percent",
                "source_series": ["CPIAUCSL"],
            }
        ],
        claims=[
            {
                "text": "CPI increased over the five-year window.",
                "metric_refs": ["cpi_five_year_change_percent"],
            }
        ],
        charts=[{"type": "line", "data": []}],
        method_notes="Computed from CPIAUCSL.",
        warnings=[],
    )


def _canonical_cpi_analysis_artifact() -> AnalysisArtifact:
    return AnalysisArtifact(
        tables=[
            {
                "name": "cpi_summary",
                "rows": [
                    {"period": "start", "date": "2021-01-01", "cpi_index": 260.0},
                    {"period": "latest", "date": "2026-01-01", "cpi_index": 320.0},
                ],
            }
        ],
        metrics=[
            {
                "name": "cpi_five_year_change_percent",
                "value": 23.08,
                "unit": "percent",
                "source_series": ["CPIAUCSL"],
            },
            {
                "name": "latest_yoy_inflation_percent",
                "value": 3.1,
                "unit": "percent",
                "source_series": ["CPIAUCSL"],
            },
            {
                "name": "latest_cpi_index",
                "value": 320.0,
                "unit": "index 1982-1984=100",
                "source_series": ["CPIAUCSL"],
            },
        ],
        claims=[
            {
                "text": "CPI is higher than it was five years ago.",
                "metric_refs": ["cpi_five_year_change_percent"],
            }
        ],
        charts=[
            {
                "type": "line",
                "title": "CPIAUCSL over the last five years",
                "data": [{"date": "2026-01-01", "value": 320.0}],
            }
        ],
        method_notes="Computed from live FRED CPIAUCSL observations.",
        warnings=[],
    )
