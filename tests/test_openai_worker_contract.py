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
from workers.openai_worker import OpenAIWorker, OpenAIWorkerError


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

    selection = OpenAIWorker(api_key="test-key").select_data(
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

    code = OpenAIWorker(api_key="test-key").write_code(
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

    draft = OpenAIWorker(api_key="test-key").draft_answer(
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
