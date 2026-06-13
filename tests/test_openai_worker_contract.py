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
