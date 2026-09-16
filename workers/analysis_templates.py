"""Deterministic analysis-code templates executed by the harness sandbox."""

from __future__ import annotations

from typing import Any

from workers.artifacts import AnalysisArtifact, DraftArtifact


def canonical_cpi_analysis_code() -> str:
    return """rows = sorted(
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


def relationship_analysis_code() -> str:
    return """observations = input_data["observations"]
series_ids = [series_id for series_id in input_data["series_ids"] if series_id in observations]
if len(series_ids) < 2:
    raise RuntimeError("Relationship analysis requires at least two fetched FRED series.")

brief = (input_data.get("metadata") or {}).get("chart_brief") or {}
brief_layout = str(brief.get("layout") or "single").lower().replace("-", "_")
brief_transforms = [str(item).lower() for item in (brief.get("transforms") or [])]
brief_title = brief.get("title") or ""
brief_units = brief.get("units") or "percent"
brief_y_label = brief.get("y_label") or "percent change"
brief_notes = brief.get("notes") or ""
brief_type = brief.get("chart_type") or "line"
brief_y0 = bool(brief.get("y_starts_at_zero"))
wants_growth = (not brief_transforms) or any(
    token in " ".join(brief_transforms)
    for token in ("growth", "yoy", "qoq", "mom", "zscore", "z-score", "percent")
)

def sorted_rows(series_id):
    return sorted(observations[series_id], key=lambda row: row["date"])

anchor_id = min(series_ids, key=lambda series_id: len(observations[series_id]))
other_ids = [series_id for series_id in series_ids if series_id != anchor_id]


def locf_value(rows, target_date):
    value = None
    for row in rows:
        if row["date"] <= target_date:
            value = row["value"]
        else:
            break
    return value

aligned = []
for row in sorted_rows(anchor_id):
    point = {"date": row["date"], anchor_id: row["value"]}
    complete = True
    for other_id in other_ids:
        value = locf_value(sorted_rows(other_id), row["date"])
        if value is None:
            complete = False
            break
        point[other_id] = value
    if complete:
        aligned.append(point)

if len(aligned) < 8:
    raise RuntimeError("Not enough overlapping observations to measure a relationship.")

growth = {series_id: [] for series_id in series_ids}
for previous, current in zip(aligned, aligned[1:]):
    for series_id in series_ids:
        prior = previous[series_id]
        growth[series_id].append(0.0 if prior == 0 else ((current[series_id] / prior) - 1.0) * 100.0)


def pearson(xs, ys):
    count = len(xs)
    mean_x = sum(xs) / count
    mean_y = sum(ys) / count
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
    denom_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5
    if denom_x == 0 or denom_y == 0:
        return 0.0
    return numerator / (denom_x * denom_y)

left_id, right_id = series_ids[0], series_ids[1]
correlation = round(pearson(growth[left_id], growth[right_id]), 4)
relationship = (
    "positive correlation"
    if correlation > 0.15
    else "anti-correlation"
    if correlation < -0.15
    else "little contemporaneous correlation"
)
chart_rows = [
    {
        "date": current["date"],
        f"{left_id}_growth": round(growth[left_id][index], 4),
        f"{right_id}_growth": round(growth[right_id][index], 4),
    }
    for index, current in enumerate(aligned[1:])
]
level_rows = [
    {"date": item["date"], left_id: item[left_id], right_id: item[right_id]}
    for item in aligned
]
latest = aligned[-1]
first = aligned[0]


def amplitude(values):
    peaks = [abs(value) for value in values if value is not None]
    return max(peaks) if peaks else 1.0

left_amp = amplitude([item[left_id] for item in aligned])
right_amp = amplitude([item[right_id] for item in aligned])
levels_incompatible = (
    min(left_amp, right_amp) > 0
    and max(left_amp, right_amp) / min(left_amp, right_amp) >= 10.0
)
overlap_n = len(growth[left_id])
growth_notes = brief_notes or (
    "Growth rates share a percent axis so the correlation is visually readable. "
    "Raw levels are not forced onto one scale. Mixed frequencies aligned with "
    "last-observation-carried-forward; overlap n is reported on the correlation metric."
)
if "overlap" not in growth_notes.lower():
    growth_notes = f"{growth_notes} Overlap n={overlap_n}."
growth_chart = {
    "type": brief_type if brief_type in {"line", "scatter", "bars", "panels"} else "line",
    "layout": "single" if wants_growth else brief_layout or "single",
    "shared_y_axis": True,
    "title": brief_title or f"Period-over-period growth in {left_id} and {right_id}",
    "x_field": "date",
    "y_field": [f"{left_id}_growth", f"{right_id}_growth"],
    "unit": brief_units or "percent",
    "y_label": brief_y_label or "percent change",
    "series_id": ",".join(series_ids),
    "series_ids": list(series_ids),
    "y_starts_at_zero": brief_y0,
    "data": chart_rows,
    "notes": growth_notes,
}
levels_layout = "stacked" if brief_layout in {"stacked", "panels", "small_multiples"} else "dual_axis"
if levels_incompatible or brief_layout in {"dual_axis", "stacked", "panels"}:
    levels_chart = {
        "type": "line",
        "layout": levels_layout if levels_incompatible or brief_layout != "single" else "dual_axis",
        "shared_y_axis": False,
        "title": f"{left_id} and {right_id} levels ({levels_layout.replace('_', ' ')})",
        "x_field": "date",
        "y_field": [left_id, right_id],
        "y_left": left_id,
        "y_right": right_id,
        "y_left_label": f"{left_id} (source units)",
        "y_right_label": f"{right_id} (source units)",
        "unit": "mixed native units",
        "series_id": ",".join(series_ids),
        "series_ids": list(series_ids),
        "y_starts_at_zero": False,
        "data": level_rows,
        "notes": (
            "Independent scales because native units differ. This companion chart is "
            "not the correlation visual; growth rates are on a shared percent axis."
        ),
    }
else:
    levels_chart = {
        "type": "line",
        "layout": "single",
        "shared_y_axis": True,
        "title": f"{left_id} and {right_id} over the overlapping window",
        "x_field": "date",
        "y_field": [left_id, right_id],
        "unit": "source units",
        "y_label": "source units",
        "series_id": ",".join(series_ids),
        "series_ids": list(series_ids),
        "y_starts_at_zero": False,
        "data": level_rows,
        "notes": "Levels share an axis because native amplitudes are comparable.",
    }

charts = [growth_chart, levels_chart] if wants_growth else [levels_chart, growth_chart]

analysis_output = {
    "tables": [
        {
            "name": "relationship_summary",
            "rows": [
                {
                    "left_series": left_id,
                    "right_series": right_id,
                    "overlap_periods": overlap_n,
                    "growth_correlation": correlation,
                    "start_date": first["date"],
                    "end_date": latest["date"],
                }
            ],
        }
    ],
    "metrics": [
        {
            "name": "growth_correlation",
            "value": correlation,
            "unit": "correlation",
            "source_series": list(series_ids),
        },
        {
            "name": "overlap_periods",
            "value": overlap_n,
            "unit": "periods",
            "source_series": list(series_ids),
        },
        {
            "name": "latest_left_value",
            "value": round(latest[left_id], 3),
            "unit": "source units",
            "source_series": [left_id],
        },
        {
            "name": "latest_right_value",
            "value": round(latest[right_id], 3),
            "unit": "source units",
            "source_series": [right_id],
        },
    ],
    "claims": [
        {
            "text": (
                f"Aligned period-over-period growth in {left_id} and {right_id} "
                f"shows {relationship}."
            ),
            "metric_refs": ["growth_correlation"],
        }
    ],
    "charts": charts,
    "method_notes": (
        "Aligned the lower-frequency series dates with last-observation-carried-forward "
        "values from higher-frequency series, then computed Pearson correlation of "
        "period-over-period percent changes. This is a contemporaneous association, "
        "not a causal estimate or a full lead-lag scan. Chart layout follows the "
        "structured chart brief when one is present in input_data metadata."
    ),
    "warnings": [
        "Series may have different native frequencies; alignment can undersample a monthly series.",
        "Correlation of growth rates is not proof of causation.",
        "The latest aligned period may be partial if the higher-frequency series has not closed.",
    ],
}
"""


def canonical_cpi_draft(analysis: AnalysisArtifact) -> DraftArtifact:
    metrics_by_name = _metrics_by_name(analysis)
    five_year = metrics_by_name["cpi_five_year_change_percent"]
    latest_yoy = metrics_by_name["latest_yoy_inflation_percent"]
    latest_index = metrics_by_name["latest_cpi_index"]
    return DraftArtifact(
        answer=(
            "Over the last five years, CPI inflation has left the CPI index "
            f"materially higher. The CPIAUCSL index increased by "
            f"{five_year.get('value')}% over the fetched five-year window, "
            f"and the latest year-over-year CPI inflation rate was "
            f"{latest_yoy.get('value')}%. The latest CPI index reading in "
            f"the analysis was {latest_index.get('value')}."
        ),
        referenced_metrics=[
            "cpi_five_year_change_percent",
            "latest_yoy_inflation_percent",
            "latest_cpi_index",
        ],
        chart_paths=_chart_paths(analysis),
    )


def relationship_draft(analysis: AnalysisArtifact) -> DraftArtifact:
    metrics_by_name = _metrics_by_name(analysis)
    correlation = metrics_by_name.get("growth_correlation", {})
    overlap = metrics_by_name.get("overlap_periods", {})
    source_series = [
        str(item)
        for item in correlation.get("source_series") or []
        if item
    ]
    if len(source_series) < 2:
        source_series = [
            str(metric.get("source_series", ["FRED"])[0])
            for metric in analysis.metrics
            if isinstance(metric, dict) and metric.get("source_series")
        ]
        source_series = list(dict.fromkeys(source_series))
    left, right = (source_series + ["series_a", "series_b"])[:2]
    value = correlation.get("value")
    if isinstance(value, (int, float)):
        if value < -0.15:
            relationship = "anti-correlated (negative contemporaneous association)"
        elif value > 0.15:
            relationship = "positively correlated"
        else:
            relationship = "only weakly contemporaneously associated"
    else:
        relationship = "associated"
    return DraftArtifact(
        answer=(
            f"Over the overlapping FRED window, period-over-period growth in {left} "
            f"and {right} is {relationship}. The Pearson correlation of aligned growth "
            f"rates is {value} across {overlap.get('value')} overlapping periods. "
            "This is a contemporaneous correlation of growth rates after aligning mixed "
            "frequencies; it is not a causal claim and does not by itself identify lead-lag."
        ),
        referenced_metrics=[
            name
            for name in ("growth_correlation", "overlap_periods", "latest_left_value", "latest_right_value")
            if name in metrics_by_name
        ],
        chart_paths=_chart_paths(analysis),
    )


def looks_like_canned_cpi_draft(draft: Any) -> bool:
    answer = ""
    if hasattr(draft, "answer"):
        answer = str(draft.answer)
    elif isinstance(draft, dict):
        answer = str(draft.get("answer") or "")
    text = answer.lower()
    return (
        "has left the cpi index materially higher" in text
        or "the cpiaucsl index increased by" in text
    ) and "correlation" not in text


def _metrics_by_name(analysis: AnalysisArtifact) -> dict[str, dict[str, Any]]:
    return {
        metric["name"]: metric
        for metric in analysis.metrics
        if isinstance(metric, dict) and isinstance(metric.get("name"), str)
    }


def _chart_paths(analysis: AnalysisArtifact) -> list[str]:
    return [
        "analysis.json#charts/0"
        for chart in analysis.charts[:1]
        if isinstance(chart, dict)
    ]
