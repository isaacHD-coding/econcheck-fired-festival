"""Deterministic mock worker for the FRED analysis loop."""

from __future__ import annotations

from typing import Any

from harness.domain import is_cpi_question, is_relationship_question
from harness.state import RunState
from workers.analysis_templates import relationship_analysis_code, relationship_draft
from workers.artifacts import (
    AnalysisArtifact,
    ChartBriefArtifact,
    CodeArtifact,
    DataArtifact,
    DataSelectionArtifact,
    DraftArtifact,
    PlannerArtifact,
)
from workers.chart_briefs import build_chart_brief, is_instruction_note


class MockWorker:
    def plan(
        self,
        question: str,
        state: RunState,
    ) -> PlannerArtifact:
        self.question = question
        if is_relationship_question(question):
            return PlannerArtifact(
                question_type="relationship",
                economic_concepts=["inflation", "real GDP growth", "correlation"],
                measurement_strategy=(
                    "Search FRED for CPIAUCSL and GDPC1, align mixed frequencies, "
                    "and measure the correlation of period-over-period growth rates."
                ),
                information_requirements=[
                    "FRED CPIAUCSL observations",
                    "FRED GDPC1 observations",
                    "overlapping dates for a correlation estimate",
                ],
                search_queries=[
                    "Consumer Price Index for All Urban Consumers All Items CPIAUCSL",
                    "Real Gross Domestic Product GDPC1",
                ],
                required_outputs=[
                    "growth-rate correlation",
                    "overlap period count",
                    "aligned dual-series chart",
                ],
                success_criteria=[
                    "Answer reports the correlation between inflation and real GDP growth",
                    "Answer cites generated metric names",
                    "Answer notes alignment caveats",
                ],
            )
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
        selected_items = _select_series_list(
            normalized,
            plan,
            getattr(self, "question", ""),
        )
        if not selected_items:
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

        selected_ids = {item.get("series_id") for item in selected_items}
        rejected = [
            {**item, "reason": item.get("reason") or "Not among the selected series."}
            for item in normalized
            if item.get("series_id") not in selected_ids
        ]
        return DataSelectionArtifact(
            selected_series=selected_items,
            rejected_series=rejected,
            justification=(
                "Selected "
                + ", ".join(str(item.get("series_id")) for item in selected_items)
                + " from live FRED search results without inventing series identifiers."
            ),
        )

    def design_chart(
        self,
        plan: PlannerArtifact,
        data_summary: DataArtifact | dict[str, Any],
    ) -> ChartBriefArtifact:
        return build_chart_brief(
            plan,
            data_summary,
            question=getattr(self, "question", ""),
        )

    def write_code(
        self,
        plan: PlannerArtifact,
        data_summary: DataArtifact | dict[str, Any],
        chart_brief: ChartBriefArtifact | None = None,
    ) -> CodeArtifact:
        series_ids = _series_ids(data_summary)
        brief = chart_brief or build_chart_brief(
            plan,
            data_summary,
            question=getattr(self, "question", ""),
        )
        _attach_chart_brief(data_summary, brief)
        if len(series_ids) > 1:
            return CodeArtifact(code=relationship_analysis_code())
        series_id = series_ids[0] if series_ids else "CPIAUCSL"
        return CodeArtifact(code=_single_series_analysis_code(series_id, brief))

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
        if any(name == "growth_correlation" for name in referenced_metrics):
            return relationship_draft(analysis)
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


def _select_series_list(
    search_results: list[dict],
    plan: PlannerArtifact,
    question: str,
) -> list[dict]:
    if not search_results:
        return []

    if is_relationship_question(question) or plan.question_type == "relationship":
        selected: list[dict] = []
        for series_id in ("CPIAUCSL", "GDPC1"):
            match = next(
                (dict(item) for item in search_results if item.get("series_id") == series_id),
                None,
            )
            if match is None:
                continue
            match["reason"] = match.get("reason") or (
                f"{series_id} is present in FRED search results and needed for the relationship."
            )
            selected.append(match)
        if selected:
            return selected
        return []

    if is_cpi_question(question) or is_cpi_question(
        " ".join(plan.search_queries + plan.economic_concepts)
    ):
        for item in search_results:
            if item.get("series_id") == "CPIAUCSL":
                chosen = dict(item)
                chosen["reason"] = "CPIAUCSL is the headline CPI index for all urban consumers."
                return [chosen]
        for item in search_results:
            title = str(item.get("title", "")).lower()
            if (
                "consumer price index for all urban consumers" in title
                and "all items" in title
            ):
                chosen = dict(item)
                chosen["reason"] = "Best matching all-items CPI series in search results."
                return [chosen]

    first = dict(search_results[0])
    first["reason"] = first.get("reason") or (
        "Best matching series from harness-provided FRED search results."
    )
    return [first]


def _series_ids(data_summary: DataArtifact | dict[str, Any]) -> list[str]:
    if hasattr(data_summary, "series_ids") and data_summary.series_ids:
        return [str(item) for item in data_summary.series_ids]
    if isinstance(data_summary, dict):
        series_ids = data_summary.get("series_ids") or []
        if series_ids:
            return [str(item) for item in series_ids]
        observations = data_summary.get("observations") or {}
        return [str(item) for item in observations]
    if hasattr(data_summary, "observations") and data_summary.observations:
        return [str(item) for item in data_summary.observations]
    return []


def _attach_chart_brief(
    data_summary: DataArtifact | dict[str, Any],
    brief: ChartBriefArtifact,
) -> None:
    payload = brief.to_dict()
    if hasattr(data_summary, "metadata") and isinstance(data_summary.metadata, dict):
        data_summary.metadata["chart_brief"] = payload
        return
    if isinstance(data_summary, dict):
        metadata = data_summary.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["chart_brief"] = payload


def _single_series_analysis_code(
    series_id: str,
    chart_brief: ChartBriefArtifact | None = None,
) -> str:
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
    title = f"{series_id} over the last five years"
    y_label = level_unit
    notes = f"Single-series levels chart of {series_id}."
    chart_type = "line"
    y_starts_at_zero = False
    layout = "single"
    if chart_brief is not None:
        title = chart_brief.title.replace('"', "'")
        y_label = chart_brief.y_label.replace('"', "'")
        notes = chart_brief.notes.replace('"', "'")
        if is_instruction_note(notes):
            notes = f"{series_id} over the fetched window."
        chart_type = chart_brief.chart_type
        y_starts_at_zero = chart_brief.y_starts_at_zero
        layout = chart_brief.layout
        if chart_brief.units:
            level_unit = chart_brief.units.replace('"', "'")
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
            "type": "{chart_type}",
            "layout": "{layout}",
            "shared_y_axis": True,
            "title": "{title}",
            "x_field": "date",
            "y_field": "value",
            "unit": "{level_unit}",
            "y_label": "{y_label}",
            "series_id": "{series_id}",
            "y_starts_at_zero": {y_starts_at_zero},
            "data": chart_rows,
            "notes": "{notes}",
        }}
    ],
    "method_notes": (
        "Computed percent changes from live FRED {series_id} observations supplied "
        "by the harness."
    ),
    "warnings": [],
}}
"""
