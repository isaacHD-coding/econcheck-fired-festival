"""Deterministic mock worker for the FRED analysis loop."""

from __future__ import annotations

from typing import Any

from harness.domain import is_cpi_question
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
        if is_cpi_question(question):
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

        return PlannerArtifact(
            question_type="trend",
            economic_concepts=["economic measurement", "time series"],
            measurement_strategy=(
                "Search FRED for series matching the question, then compare the "
                "latest observation with the start of the fetched window."
            ),
            information_requirements=[
                "FRED series identifier",
                "observations covering the last five years",
            ],
            search_queries=[question.strip()],
            required_outputs=[
                "five-year percent change",
                "latest value",
                "line chart data",
            ],
            success_criteria=[
                "Answer references selected FRED evidence",
                "Answer cites generated metric names",
                "Answer describes the direction of the series over five years",
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
        selected = _select_series(normalized, plan)
        if selected is None:
            return DataSelectionArtifact(
                selected_series=[],
                rejected_series=[
                    {**item, "reason": item.get("reason") or "No justified primary series."}
                    for item in normalized
                ],
                justification=(
                    "No FRED search result could be selected without inventing a series."
                ),
            )

        selected = dict(selected)
        selected["reason"] = selected.get("reason") or (
            "Best matching series from harness-provided FRED search results."
        )
        rejected = [
            {**item, "reason": item.get("reason") or "Not the selected primary series."}
            for item in normalized
            if item.get("series_id") != selected.get("series_id")
        ]
        return DataSelectionArtifact(
            selected_series=[selected],
            rejected_series=rejected,
            justification=(
                f"Selected {selected.get('series_id')} from live FRED search results "
                "because it best matches the planner search target."
            ),
        )

    def write_code(
        self,
        plan: PlannerArtifact,
        data_summary: DataArtifact | dict[str, Any],
    ) -> CodeArtifact:
        series_id = _primary_series_id(data_summary)
        return CodeArtifact(code=_analysis_code(series_id))

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
        five_year = (
            metrics_by_name.get("cpi_five_year_change_percent")
            or metrics_by_name.get("five_year_change_percent")
            or {}
        )
        latest_yoy = (
            metrics_by_name.get("latest_yoy_inflation_percent")
            or metrics_by_name.get("latest_yoy_change_percent")
            or {}
        )
        latest_index = (
            metrics_by_name.get("latest_cpi_index")
            or metrics_by_name.get("latest_value")
            or {}
        )
        chart_paths = [
            "analysis.json#charts/0"
            for chart in analysis.charts[:1]
            if isinstance(chart, dict)
        ]
        source_series = next(
            (
                metric.get("source_series", ["FRED"])[0]
                for metric in analysis.metrics
                if isinstance(metric, dict) and metric.get("source_series")
            ),
            "the selected FRED series",
        )
        cpi_language = source_series == "CPIAUCSL"
        subject = "CPI inflation" if cpi_language else f"{source_series} conditions"
        series_label = "The CPIAUCSL index" if cpi_language else f"The {source_series} series"

        return DraftArtifact(
            answer=(
                f"Over the last five years, {subject} left the series materially changed. "
                f"{series_label} changed by {five_year.get('value')}% over the fetched "
                f"five-year window, and the latest year-over-year change was "
                f"{latest_yoy.get('value')}%. The latest reading in the analysis was "
                f"{latest_index.get('value')}."
            ),
            referenced_metrics=referenced_metrics,
            chart_paths=chart_paths,
        )


def _select_series(search_results: list[dict], plan: PlannerArtifact) -> dict | None:
    if not search_results:
        return None

    if is_cpi_question(" ".join(plan.search_queries + plan.economic_concepts)):
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

    return dict(search_results[0])


def _primary_series_id(data_summary: DataArtifact | dict[str, Any]) -> str:
    if hasattr(data_summary, "series_ids") and data_summary.series_ids:
        return str(data_summary.series_ids[0])
    if isinstance(data_summary, dict):
        series_ids = data_summary.get("series_ids") or []
        if series_ids:
            return str(series_ids[0])
        observations = data_summary.get("observations") or {}
        if observations:
            return str(next(iter(observations)))
    if hasattr(data_summary, "observations") and data_summary.observations:
        return str(next(iter(data_summary.observations)))
    return "CPIAUCSL"


def _analysis_code(series_id: str) -> str:
    cpi = series_id == "CPIAUCSL"
    five_year_name = "cpi_five_year_change_percent" if cpi else "five_year_change_percent"
    yoy_name = "latest_yoy_inflation_percent" if cpi else "latest_yoy_change_percent"
    level_name = "latest_cpi_index" if cpi else "latest_value"
    level_unit = "index 1982-1984=100" if cpi else "source units"
    claim_text = (
        "CPI is higher than it was five years ago."
        if cpi
        else f"{series_id} changed over the fetched window."
    )
    return f"""rows = sorted(
    input_data["observations"]["{series_id}"],
    key=lambda row: row["date"],
)
if len(rows) < 8:
    raise RuntimeError("Expected enough observations for a five-year analysis.")

latest = rows[-1]
first = rows[0]
yoy_reference = rows[-13] if len(rows) >= 13 else rows[0]

five_year_change = ((latest["value"] / first["value"]) - 1.0) * 100.0
latest_yoy = ((latest["value"] / yoy_reference["value"]) - 1.0) * 100.0

chart_rows = [
    {{"date": row["date"], "value": row["value"]}}
    for row in rows
]

analysis_output = {{
    "tables": [
        {{
            "name": "series_summary",
            "rows": [
                {{
                    "period": "start",
                    "date": first["date"],
                    "value": round(first["value"], 3),
                }},
                {{
                    "period": "latest",
                    "date": latest["date"],
                    "value": round(latest["value"], 3),
                }},
                {{
                    "period": "year_ago",
                    "date": yoy_reference["date"],
                    "value": round(yoy_reference["value"], 3),
                }},
            ],
        }}
    ],
    "metrics": [
        {{
            "name": "{five_year_name}",
            "value": round(five_year_change, 2),
            "unit": "percent",
            "source_series": ["{series_id}"],
        }},
        {{
            "name": "{yoy_name}",
            "value": round(latest_yoy, 2),
            "unit": "percent",
            "source_series": ["{series_id}"],
        }},
        {{
            "name": "{level_name}",
            "value": round(latest["value"], 3),
            "unit": "{level_unit}",
            "source_series": ["{series_id}"],
        }},
    ],
    "claims": [
        {{
            "text": "{claim_text}",
            "metric_refs": ["{five_year_name}"],
        }},
        {{
            "text": "The latest year-over-year change is calculated from {series_id}.",
            "metric_refs": ["{yoy_name}"],
        }},
    ],
    "charts": [
        {{
            "type": "line",
            "title": "{series_id} over the last five years",
            "x_field": "date",
            "y_field": "value",
            "unit": "{level_unit}",
            "series_id": "{series_id}",
            "data": chart_rows,
        }}
    ],
    "method_notes": (
        "Computed percent changes from live FRED {series_id} observations supplied "
        "by the harness."
    ),
    "warnings": [],
}}
"""
