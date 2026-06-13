"""Deterministic mock worker for Milestone 4 contract tests."""

from __future__ import annotations

from harness.state import RunState
from workers.artifacts import (
    AnalysisArtifact,
    CodeArtifact,
    DataSelectionArtifact,
    DraftArtifact,
    PlannerArtifact,
)


class MockWorker:
    def plan(
        self,
        question: str,
        state: RunState,
    ) -> PlannerArtifact:
        return PlannerArtifact(
            question_type="trend",
            economic_concepts=["inflation", "consumer prices"],
            measurement_strategy="Compare CPI levels and inflation metrics over time.",
            information_requirements=[
                "CPI series identifier",
                "recent CPI observations",
            ],
            search_queries=["consumer price index all urban consumers"],
            required_outputs=[
                "summary of CPI movement",
                "supporting metric references",
            ],
            success_criteria=[
                "Answer references selected CPI evidence",
                "Answer avoids unsupported numeric claims",
            ],
        )

    def select_data(
        self,
        plan: PlannerArtifact,
        search_results: list,
    ) -> DataSelectionArtifact:
        if search_results and isinstance(search_results[0], dict):
            selected = dict(search_results[0])
            selected.setdefault("series_id", "CPIAUCSL")
            selected.setdefault("reason", "First mock search result selected.")
        else:
            selected = {
                "series_id": "CPIAUCSL",
                "reason": "Mock default CPI series selection.",
            }

        return DataSelectionArtifact(
            selected_series=[selected],
            rejected_series=[],
            justification="Mock worker selects a CPI series for contract testing.",
        )

    def write_code(
        self,
        plan: PlannerArtifact,
        data_summary: "DataArtifact",
    ) -> CodeArtifact:
        code = """def analyze(data):
    return {
        "tables": [],
        "metrics": [],
        "claims": [],
        "charts": [],
        "method_notes": "Mock worker code only.",
        "warnings": [],
    }
"""
        return CodeArtifact(code=code)

    def draft_answer(
        self,
        plan: PlannerArtifact,
        analysis: AnalysisArtifact,
    ) -> DraftArtifact:
        referenced_metrics = [
            metric["name"]
            for metric in analysis.metrics
            if isinstance(metric, dict) and isinstance(metric.get("name"), str)
        ]
        chart_paths = [chart for chart in analysis.charts if isinstance(chart, str)]

        return DraftArtifact(
            answer="Mock answer based on the supplied analysis artifact.",
            referenced_metrics=referenced_metrics,
            chart_paths=chart_paths,
        )
