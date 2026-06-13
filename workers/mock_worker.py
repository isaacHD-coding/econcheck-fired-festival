"""Deterministic mock worker for Milestone 4 contract tests."""

from __future__ import annotations

from harness.state import RunState
from workers.artifacts import (
    AnalysisArtifact,
    CodeArtifact,
    DataArtifact,
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
            measurement_strategy=(
                "Use the FRED CPIAUCSL index to compare the latest CPI level "
                "with the level five years earlier and compute the latest "
                "year-over-year inflation rate."
            ),
            information_requirements=[
                "FRED CPI series identifier",
                "monthly CPI observations covering the last five years",
            ],
            search_queries=[
                "Consumer Price Index for All Urban Consumers All Items CPIAUCSL"
            ],
            required_outputs=[
                "five-year CPI percent change",
                "latest year-over-year CPI inflation rate",
                "CPI line chart data",
            ],
            success_criteria=[
                "Answer references selected CPI evidence from FRED",
                "Answer cites generated metric names",
                "Answer describes the direction of CPI inflation over five years",
            ],
        )

    def select_data(
        self,
        plan: PlannerArtifact,
        search_results: list,
    ) -> DataSelectionArtifact:
        normalized = [
            item.to_dict() if hasattr(item, "to_dict") else dict(item)
            for item in search_results
            if hasattr(item, "to_dict") or isinstance(item, dict)
        ]
        selected = _select_cpi_series(normalized)
        selected["reason"] = "CPIAUCSL is the headline CPI index for all urban consumers."
        rejected = [
            {**item, "reason": "Not the primary CPIAUCSL all-items index."}
            for item in normalized
            if item.get("series_id") != selected.get("series_id")
        ]

        return DataSelectionArtifact(
            selected_series=[selected],
            rejected_series=rejected,
            justification=(
                "The mock worker selects CPIAUCSL because it is the standard "
                "monthly all-items Consumer Price Index series in FRED."
            ),
        )

    def write_code(
        self,
        plan: PlannerArtifact,
        data_summary: DataArtifact,
    ) -> CodeArtifact:
        code = """from datetime import datetime

rows = sorted(
    input_data["observations"]["CPIAUCSL"],
    key=lambda row: row["date"],
)
if len(rows) < 48:
    raise RuntimeError("Expected at least 48 CPI observations for five-year analysis.")

latest = rows[-1]
first = rows[0]
yoy_reference = rows[-13] if len(rows) >= 13 else rows[0]

five_year_change = ((latest["value"] / first["value"]) - 1.0) * 100.0
latest_yoy = ((latest["value"] / yoy_reference["value"]) - 1.0) * 100.0

chart_rows = [
    {"date": row["date"], "value": row["value"]}
    for row in rows
]

analysis_output = {
    "tables": [
        {
            "name": "cpi_summary",
            "rows": [
                {
                    "period": "start",
                    "date": first["date"],
                    "cpi_index": round(first["value"], 3),
                },
                {
                    "period": "latest",
                    "date": latest["date"],
                    "cpi_index": round(latest["value"], 3),
                },
                {
                    "period": "year_ago",
                    "date": yoy_reference["date"],
                    "cpi_index": round(yoy_reference["value"], 3),
                },
            ],
        }
    ],
    "metrics": [
        {
            "name": "cpi_five_year_change_percent",
            "value": round(five_year_change, 2),
            "unit": "percent",
            "source_series": ["CPIAUCSL"],
        },
        {
            "name": "latest_yoy_inflation_percent",
            "value": round(latest_yoy, 2),
            "unit": "percent",
            "source_series": ["CPIAUCSL"],
        },
        {
            "name": "latest_cpi_index",
            "value": round(latest["value"], 3),
            "unit": "index 1982-1984=100",
            "source_series": ["CPIAUCSL"],
        },
    ],
    "claims": [
        {
            "text": "CPI is higher than it was five years ago.",
            "metric_refs": ["cpi_five_year_change_percent"],
        },
        {
            "text": "The latest year-over-year CPI inflation rate is calculated from CPIAUCSL.",
            "metric_refs": ["latest_yoy_inflation_percent"],
        },
    ],
    "charts": [
        {
            "type": "line",
            "title": "CPIAUCSL over the last five years",
            "x_field": "date",
            "y_field": "value",
            "unit": "index 1982-1984=100",
            "series_id": "CPIAUCSL",
            "data": chart_rows,
        }
    ],
    "method_notes": (
        "Computed percent changes from live FRED CPIAUCSL observations supplied "
        "by the harness."
    ),
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
        metrics_by_name = {
            metric["name"]: metric
            for metric in analysis.metrics
            if isinstance(metric, dict) and isinstance(metric.get("name"), str)
        }
        five_year = metrics_by_name.get("cpi_five_year_change_percent", {})
        latest_yoy = metrics_by_name.get("latest_yoy_inflation_percent", {})
        latest_index = metrics_by_name.get("latest_cpi_index", {})
        chart_paths = [
            "analysis.json#charts/0"
            for chart in analysis.charts[:1]
            if isinstance(chart, dict)
        ]

        return DraftArtifact(
            answer=(
                "Over the last five years, CPI inflation has left the CPI index "
                f"materially higher. The CPIAUCSL index increased by "
                f"{five_year.get('value')}% over the fetched five-year window, "
                f"and the latest year-over-year CPI inflation rate was "
                f"{latest_yoy.get('value')}%. The latest CPI index reading in "
                f"the analysis was {latest_index.get('value')}."
            ),
            referenced_metrics=referenced_metrics,
            chart_paths=chart_paths,
        )


def _select_cpi_series(search_results: list[dict]) -> dict:
    for item in search_results:
        if item.get("series_id") == "CPIAUCSL":
            return dict(item)

    for item in search_results:
        title = str(item.get("title", "")).lower()
        if (
            "consumer price index for all urban consumers" in title
            and "all items" in title
        ):
            return dict(item)

    return {
        "series_id": "CPIAUCSL",
        "title": "Consumer Price Index for All Urban Consumers: All Items in U.S. City Average",
        "frequency": "Monthly",
        "units": "Index 1982-1984=100",
        "observation_start": "",
        "observation_end": "",
    }
