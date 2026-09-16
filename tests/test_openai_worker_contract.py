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
    OPENAI_DESIGN_CHART_TIMEOUT_SECONDS,
    OPENAI_PLAN_TIMEOUT_SECONDS,
    OPENAI_WRITE_CODE_TIMEOUT_SECONDS,
    OpenAITimeoutError,
)
from workers.openai_worker import OpenAIWorker, OpenAIWorkerError, OpenAIWorkerTimeoutError


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
    plan = worker.plan(QUESTION, state)
    worker.design_chart(plan, _data_artifact())
    worker.write_code(plan, _data_artifact())

    assert captured["planner_artifact"] == OPENAI_PLAN_TIMEOUT_SECONDS
    assert captured["chart_brief_artifact"] == OPENAI_DESIGN_CHART_TIMEOUT_SECONDS
    assert captured["code_artifact"] == OPENAI_WRITE_CODE_TIMEOUT_SECONDS


def test_openai_worker_timeout_raises_friendly_error(monkeypatch) -> None:
    def fake_call_openai_json(**kwargs):
        raise OpenAITimeoutError(
            "code_artifact",
            OPENAI_WRITE_CODE_TIMEOUT_SECONDS,
            stage_label="write_code",
        )

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    with pytest.raises(OpenAIWorkerTimeoutError, match="Code generation took longer than 120") as err:
        worker.write_code(_planner_artifact(), _data_artifact())

    assert "did not match" not in str(err.value)
    assert "OpenAIWorkerError" not in str(err.value)
    assert err.value.timeout_seconds == OPENAI_WRITE_CODE_TIMEOUT_SECONDS
    assert err.value.stage_label == "write_code"


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


def test_openai_worker_uses_executable_canonical_cpi_code_after_model_call(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_call_openai_json(*, schema_name, **kwargs):
        calls.append(schema_name)
        return {"code": "analysis_output = {'tables': {'bad': 'shape'}}"}

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = QUESTION
    code = worker.write_code(
        _planner_artifact(),
        _canonical_cpi_data_artifact(),
    )
    analysis = run_analysis_code(code, _canonical_cpi_data_artifact())

    assert calls == ["code_artifact"]
    assert analysis.tables
    assert analysis.metrics
    assert analysis.charts
    assert {metric["name"] for metric in analysis.metrics} >= {
        "cpi_five_year_change_percent",
        "latest_yoy_inflation_percent",
        "latest_cpi_index",
    }


def test_openai_worker_uses_grounded_canonical_cpi_draft_after_model_call(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_call_openai_json(*, schema_name, **kwargs):
        calls.append(schema_name)
        return {
            "answer": "Prices changed.",
            "referenced_metrics": [],
            "chart_paths": [],
        }

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = QUESTION
    draft = worker.draft_answer(
        _planner_artifact(),
        _canonical_cpi_analysis_artifact(),
    )

    assert calls == ["draft_artifact"]
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


def test_openai_worker_replaces_canonical_cpi_code_when_plan_needs_gdp(
    monkeypatch,
) -> None:
    def fake_call_openai_json(*, schema_name, **kwargs):
        return {
            "code": (
                "rows = sorted(input_data['observations']['CPIAUCSL'], "
                "key=lambda row: row['date'])\n"
                "if len(rows) < 48:\n"
                "    raise RuntimeError('Expected at least 48 CPI observations "
                "for five-year analysis.')\n"
                "analysis_output = {'tables': [], 'metrics': [], 'claims': [], "
                "'charts': [], 'method_notes': 'canned-cpi', 'warnings': []}"
            )
        }

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = ISAAC_QUESTION
    code = worker.write_code(_relationship_plan(), _cpi_and_gdp_data())

    assert "Expected at least 48 CPI observations" not in code.code
    assert "growth_correlation" in code.code
    assert "pearson" in code.code


def test_openai_worker_does_not_replace_multiseries_model_code_with_canonical_cpi(
    monkeypatch,
) -> None:
    model_code = (
        "analysis_output = {"
        "'tables': [], "
        "'metrics': [{'name': 'inflation_gdp_correlation', 'value': -0.42, "
        "'unit': 'correlation', 'source_series': ['CPIAUCSL', 'GDPC1']}], "
        "'claims': [{'text': 'Inflation and real GDP growth are anti-correlated.', "
        "'metric_refs': ['inflation_gdp_correlation']}], "
        "'charts': [{'type': 'line', 'title': 'CPIAUCSL vs GDPC1', 'data': []}], "
        "'method_notes': 'model-correlation-code', "
        "'warnings': []}"
    )

    def fake_call_openai_json(*, schema_name, **kwargs):
        assert schema_name == "code_artifact"
        return {"code": model_code}

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = ISAAC_QUESTION
    code = worker.write_code(_relationship_plan(), _cpi_and_gdp_data())

    assert "model-correlation-code" in code.code
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


def test_openai_worker_keeps_model_correlation_draft(monkeypatch) -> None:
    def fake_call_openai_json(*, schema_name, **kwargs):
        return {
            "answer": (
                "Inflation and real GDP growth are anti-correlated over the window "
                "based on growth_correlation."
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

    assert "anti-correlated" in draft.answer
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


def test_openai_worker_design_chart_falls_back_when_model_json_is_invalid(monkeypatch) -> None:
    def fake_call_openai_json(*, schema_name, **kwargs):
        assert schema_name == "chart_brief_artifact"
        return {"claim": "incomplete"}

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = ISAAC_QUESTION
    brief = worker.design_chart(_relationship_plan(), _cpi_and_gdp_data())

    assert set(brief.series_ids) == {"CPIAUCSL", "GDPC1"}
    assert "growth" in brief.transforms


def test_openai_worker_write_code_includes_chart_brief_and_design_advice(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_call_openai_json(*, schema_name, instructions, input_payload, **kwargs):
        captured["schema_name"] = schema_name
        captured["instructions"] = instructions
        captured["payload"] = input_payload
        return {
            "code": (
                "analysis_output = {"
                "'tables': [], "
                "'metrics': [], "
                "'claims': [], "
                "'charts': [{'type': 'line', 'title': 'CPIAUCSL vs GDPC1', 'data': []}], "
                "'method_notes': 'model-correlation-code', "
                "'warnings': []}"
            )
        }

    monkeypatch.setattr("workers.openai_worker.call_openai_json", fake_call_openai_json)

    worker = OpenAIWorker(api_key="test-key")
    worker.question = ISAAC_QUESTION
    brief = worker.design_chart(_relationship_plan(), _cpi_and_gdp_data())
    worker.write_code(_relationship_plan(), _cpi_and_gdp_data(), chart_brief=brief)

    assert captured["schema_name"] == "code_artifact"
    instructions = str(captured["instructions"])
    assert "Follow chart_brief for layout" in instructions
    assert "dwarf" in instructions.lower()
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["chart_brief"]["series_ids"] == brief.series_ids
    assert "growth" in payload["chart_brief"]["transforms"]


def test_relationship_analysis_code_runs_for_cpi_and_gdp() -> None:
    from workers.analysis_templates import relationship_analysis_code

    analysis = run_analysis_code(
        CodeArtifact(code=relationship_analysis_code()),
        _cpi_and_gdp_data(),
    )

    metric_names = {metric["name"] for metric in analysis.metrics}
    assert "growth_correlation" in metric_names
    assert {metric["name"] for metric in analysis.metrics if metric.get("source_series")}
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
