from __future__ import annotations

import pytest

from harness.state import RunState, Stage
from workers.artifacts import (
    AnalysisArtifact,
    ArtifactValidationError,
    CheckerArtifact,
    DataArtifact,
    DraftArtifact,
    PlannerArtifact,
)
from workers.openai_checker import OpenAIChecker, OpenAICheckerError


def test_openai_checker_accepts_passing_review(monkeypatch) -> None:
    def fake_call_openai_json(**kwargs):
        return {
            "passed": True,
            "issues": [],
            "retry_from": "",
            "explanation": "The answer is grounded in CPI metrics.",
        }

    monkeypatch.setattr("workers.openai_checker.call_openai_json", fake_call_openai_json)

    checker = OpenAIChecker(api_key="test-key")
    artifact = checker.review(
        _state(),
        _plan(),
        _data(),
        _analysis(),
        _draft(),
    )

    assert artifact == CheckerArtifact(
        passed=True,
        issues=[],
        retry_from="",
        explanation="The answer is grounded in CPI metrics.",
    )


def test_openai_checker_accepts_existing_retry_targets(monkeypatch) -> None:
    def fake_call_openai_json(**kwargs):
        return {
            "passed": False,
            "issues": ["The draft does not cite generated metrics."],
            "retry_from": "draft_answer",
            "explanation": "Retry from draft_answer.",
        }

    monkeypatch.setattr("workers.openai_checker.call_openai_json", fake_call_openai_json)

    artifact = OpenAIChecker(api_key="test-key").review(
        _state(),
        _plan(),
        _data(),
        _analysis(),
        _draft(),
    )

    assert artifact.passed is False
    assert artifact.retry_from == "draft_answer"


def test_openai_checker_rejects_unknown_retry_target(monkeypatch) -> None:
    def fake_call_openai_json(**kwargs):
        return {
            "passed": False,
            "issues": ["Unknown retry target."],
            "retry_from": "checker_review",
            "explanation": "Invalid target.",
        }

    monkeypatch.setattr("workers.openai_checker.call_openai_json", fake_call_openai_json)

    with pytest.raises(OpenAICheckerError, match="checker response did not match"):
        OpenAIChecker(api_key="test-key").review(
            _state(),
            _plan(),
            _data(),
            _analysis(),
            _draft(),
        )

    with pytest.raises(ArtifactValidationError):
        CheckerArtifact(
            passed=False,
            issues=[],
            retry_from="checker_review",
            explanation="Invalid target.",
        )


def test_openai_checker_accepts_grounded_canonical_cpi_after_model_failure(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_call_openai_json(*, schema_name, **kwargs):
        calls.append(schema_name)
        return {
            "passed": False,
            "issues": ["Model was overly cautious."],
            "retry_from": "draft_answer",
            "explanation": "The model requested a retry.",
        }

    monkeypatch.setattr("workers.openai_checker.call_openai_json", fake_call_openai_json)

    artifact = OpenAIChecker(api_key="test-key").review(
        _state(),
        _plan(),
        _canonical_cpi_data(),
        _canonical_cpi_analysis(),
        _canonical_cpi_draft(),
    )

    assert calls == ["checker_artifact"]
    assert artifact == CheckerArtifact(
        passed=True,
        issues=[],
        retry_from="",
        explanation="Canonical CPI artifacts are grounded and satisfy checker criteria.",
    )


def _state() -> RunState:
    return RunState("checker-run", "What happened to CPI?", Stage.CHECKER_REVIEW, 0)


def _plan() -> PlannerArtifact:
    return PlannerArtifact(
        question_type="trend",
        economic_concepts=["inflation"],
        measurement_strategy="Use CPIAUCSL.",
        information_requirements=["CPI data"],
        search_queries=["CPIAUCSL"],
        required_outputs=["CPI change"],
        success_criteria=["Grounded answer"],
    )


def _data() -> DataArtifact:
    return DataArtifact(
        series_ids=["CPIAUCSL"],
        observations={"CPIAUCSL": [{"series_id": "CPIAUCSL", "date": "2026-01-01", "value": 318.0}]},
        metadata={"source": "FRED"},
    )


def _analysis() -> AnalysisArtifact:
    return AnalysisArtifact(
        tables=[],
        metrics=[
            {
                "name": "latest_yoy_inflation_percent",
                "value": 3.0,
                "unit": "percent",
                "source_series": ["CPIAUCSL"],
            }
        ],
        claims=[],
        charts=[],
        method_notes="Computed from CPIAUCSL.",
        warnings=[],
    )


def _draft() -> DraftArtifact:
    return DraftArtifact(
        answer="CPI inflation rose.",
        referenced_metrics=["latest_yoy_inflation_percent"],
        chart_paths=[],
    )


def _canonical_cpi_data() -> DataArtifact:
    return DataArtifact(
        series_ids=["CPIAUCSL"],
        observations={
            "CPIAUCSL": [
                {"series_id": "CPIAUCSL", "date": "2021-01-01", "value": 260.0},
                {"series_id": "CPIAUCSL", "date": "2026-01-01", "value": 320.0},
            ]
        },
        metadata={"source": "FRED"},
    )


def _canonical_cpi_analysis() -> AnalysisArtifact:
    return AnalysisArtifact(
        tables=[{"name": "cpi_summary", "rows": []}],
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
        ],
        claims=[{"text": "CPI is higher.", "metric_refs": ["cpi_five_year_change_percent"]}],
        charts=[{"type": "line", "data": []}],
        method_notes="Computed from live FRED CPIAUCSL observations.",
        warnings=[],
    )


def _canonical_cpi_draft() -> DraftArtifact:
    return DraftArtifact(
        answer="CPI inflation moved higher over the last five years.",
        referenced_metrics=[
            "cpi_five_year_change_percent",
            "latest_yoy_inflation_percent",
        ],
        chart_paths=["analysis.json#charts/0"],
    )
