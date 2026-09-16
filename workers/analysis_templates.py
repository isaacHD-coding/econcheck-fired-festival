"""Deterministic analysis-code templates executed by the harness sandbox."""

from __future__ import annotations

from typing import Any

from workers.artifacts import AnalysisArtifact, DraftArtifact
from workers.chart_briefs import plain_series_name, result_phrase, series_name_aliases


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
SERIES_NAMES = {
    "CPIAUCSL": {"name": "CPI all items", "growth": "CPI growth", "level": "CPI all items"},
    "GDPC1": {"name": "real GDP", "growth": "Real GDP growth", "level": "Real GDP"},
    "UNRATE": {"name": "unemployment rate", "growth": "Unemployment rate change", "level": "Unemployment rate"},
}

def series_name(series_id, kind="name"):
    info = SERIES_NAMES.get(series_id) or {}
    if kind == "growth":
        return info.get("growth") or (series_id + " growth")
    if kind == "level":
        return info.get("level") or series_id
    return info.get("name") or series_id

def notes_are_instructions(text):
    blob = " ".join(str(text or "").lower().split())
    if not blob:
        return False
    if blob.startswith("do not "):
        return True
    markers = (
        "do not place incompatible",
        "if a levels companion",
        "use dual-axis or stacked",
        "plot comparable growth rates on one percent",
        "follow the chart brief",
    )
    return any(marker in blob for marker in markers)

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
left_name = series_name(left_id)
right_name = series_name(right_id)
correlation = round(pearson(growth[left_id], growth[right_id]), 4)
relationship = (
    "moved together"
    if correlation > 0.15
    else "moved opposite each other"
    if correlation < -0.15
    else "showed little relationship"
)
left_growth_field = f"{left_id}_growth"
right_growth_field = f"{right_id}_growth"
chart_rows = [
    {
        "date": current["date"],
        left_growth_field: round(growth[left_id][index], 4),
        right_growth_field: round(growth[right_id][index], 4),
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
if notes_are_instructions(brief_notes):
    brief_notes = ""
growth_notes = brief_notes or (
    f"Percent change in {left_name} ({left_id}) and {right_name} ({right_id}) "
    f"after aligning mixed frequencies ({overlap_n} overlapping periods)."
)
if "overlap" not in growth_notes.lower() and f"{overlap_n}" not in growth_notes:
    growth_notes = f"{growth_notes} {overlap_n} overlapping periods."
growth_title = brief_title if brief_title and "vs" in brief_title.lower() else (
    f"{series_name(left_id, 'growth')} vs {series_name(right_id, 'growth')}"
)
growth_chart = {
    "type": brief_type if brief_type in {"line", "scatter", "bars", "panels"} else "line",
    "layout": "single" if wants_growth else brief_layout or "single",
    "shared_y_axis": True,
    "title": growth_title,
    "x_field": "date",
    "y_field": [left_growth_field, right_growth_field],
    "unit": brief_units or "percent",
    "y_label": brief_y_label or "percent change",
    "series_id": ",".join(series_ids),
    "series_ids": list(series_ids),
    "y_starts_at_zero": brief_y0,
    "legend": {
        left_growth_field: series_name(left_id, "growth"),
        right_growth_field: series_name(right_id, "growth"),
    },
    "data": chart_rows,
    "notes": growth_notes,
}
levels_layout = "stacked" if brief_layout in {"stacked", "panels", "small_multiples"} else "dual_axis"
if levels_incompatible or brief_layout in {"dual_axis", "stacked", "panels"}:
    levels_chart = {
        "type": "line",
        "layout": levels_layout if levels_incompatible or brief_layout != "single" else "dual_axis",
        "shared_y_axis": False,
        "title": f"{series_name(left_id, 'level')} and {series_name(right_id, 'level')} levels",
        "x_field": "date",
        "y_field": [left_id, right_id],
        "y_left": left_id,
        "y_right": right_id,
        "y_left_label": f"{series_name(left_id, 'level')} ({left_id})",
        "y_right_label": f"{series_name(right_id, 'level')} ({right_id})",
        "unit": "mixed native units",
        "series_id": ",".join(series_ids),
        "series_ids": list(series_ids),
        "y_starts_at_zero": False,
        "legend": {
            left_id: series_name(left_id, "level"),
            right_id: series_name(right_id, "level"),
        },
        "data": level_rows,
        "notes": (
            f"{left_name} ({left_id}) and {right_name} ({right_id}) in native units, "
            "each on its own scale."
        ),
    }
else:
    levels_chart = {
        "type": "line",
        "layout": "single",
        "shared_y_axis": True,
        "title": f"{series_name(left_id, 'level')} and {series_name(right_id, 'level')}",
        "x_field": "date",
        "y_field": [left_id, right_id],
        "unit": "source units",
        "y_label": "source units",
        "series_id": ",".join(series_ids),
        "series_ids": list(series_ids),
        "y_starts_at_zero": False,
        "legend": {
            left_id: series_name(left_id, "level"),
            right_id: series_name(right_id, "level"),
        },
        "data": level_rows,
        "notes": f"{left_name} ({left_id}) and {right_name} ({right_id}) in native units.",
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
                f"{left_name} ({left_id}) and {right_name} ({right_id}) growth "
                f"{relationship}."
            ),
            "metric_refs": ["growth_correlation"],
        }
    ],
    "charts": charts,
    "method_notes": (
        "Aligned the lower-frequency series dates with last-observation-carried-forward "
        "values from higher-frequency series, then computed Pearson correlation of "
        "period-over-period percent changes. This is a contemporaneous association, "
        "not a causal estimate or a full lead-lag scan."
    ),
    "warnings": [
        "Series may have different native frequencies; alignment can undersample a monthly series.",
        "Correlation of growth rates is not proof of causation.",
        "The latest aligned period may be partial if the higher-frequency series has not closed.",
    ],
}
"""


def comparison_analysis_code() -> str:
    return """observations = input_data["observations"]
series_ids = [series_id for series_id in input_data["series_ids"] if series_id in observations]
if len(series_ids) < 2:
    raise RuntimeError("Comparison analysis requires at least two fetched FRED series.")

brief = (input_data.get("metadata") or {}).get("chart_brief") or {}
brief_title = brief.get("title") or ""
brief_notes = brief.get("notes") or ""
brief_type = brief.get("chart_type") or "line"
brief_y0 = bool(brief.get("y_starts_at_zero"))
SERIES_NAMES = {
    "CPIAUCSL": {"name": "CPI all items", "growth": "CPI inflation", "level": "CPI all items"},
    "PCEPI": {"name": "PCE price index", "growth": "PCE inflation", "level": "PCE price index"},
    "GDPC1": {"name": "real GDP", "growth": "Real GDP growth", "level": "Real GDP"},
}

def series_name(series_id, kind="name"):
    info = SERIES_NAMES.get(series_id) or {}
    if kind == "growth":
        return info.get("growth") or (series_id + " inflation")
    if kind == "level":
        return info.get("level") or series_id
    return info.get("name") or series_id

def notes_are_instructions(text):
    blob = " ".join(str(text or "").lower().split())
    if not blob:
        return False
    if blob.startswith("do not "):
        return True
    return "do not place" in blob

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

if len(aligned) < 13:
    raise RuntimeError("Not enough overlapping observations for year-over-year comparison.")

left_id, right_id = series_ids[0], series_ids[1]
lag = 12 if len(aligned) >= 24 else 4
yoy_rows = []
gaps = []
for index in range(lag, len(aligned)):
    current = aligned[index]
    prior = aligned[index - lag]
    left_yoy = 0.0 if prior[left_id] == 0 else ((current[left_id] / prior[left_id]) - 1.0) * 100.0
    right_yoy = 0.0 if prior[right_id] == 0 else ((current[right_id] / prior[right_id]) - 1.0) * 100.0
    gap = left_yoy - right_yoy
    gaps.append(gap)
    yoy_rows.append({
        "date": current["date"],
        left_id + "_yoy": round(left_yoy, 4),
        right_id + "_yoy": round(right_yoy, 4),
        "inflation_gap": round(gap, 4),
    })

latest = yoy_rows[-1]
latest_left = latest[left_id + "_yoy"]
latest_right = latest[right_id + "_yoy"]
latest_gap = latest["inflation_gap"]
avg_gap = sum(gaps) / len(gaps)
left_field = left_id + "_yoy"
right_field = right_id + "_yoy"
if notes_are_instructions(brief_notes):
    brief_notes = ""
notes = brief_notes or (
    "Year-over-year percent change in "
    + series_name(left_id)
    + " (" + left_id + ") and "
    + series_name(right_id)
    + " (" + right_id + "), "
    + str(len(yoy_rows))
    + " overlapping periods."
)
title = brief_title if brief_title else (
    series_name(left_id, "growth") + " vs " + series_name(right_id, "growth")
)
direction = "above" if latest_gap > 0 else "below" if latest_gap < 0 else "in line with"

analysis_output = {
    "tables": [
        {
            "name": "inflation_comparison",
            "rows": [
                {
                    "left_series": left_id,
                    "right_series": right_id,
                    "latest_left_yoy": round(latest_left, 2),
                    "latest_right_yoy": round(latest_right, 2),
                    "latest_inflation_gap": round(latest_gap, 2),
                    "five_year_average_gap": round(avg_gap, 2),
                    "overlap_periods": len(yoy_rows),
                    "end_date": latest["date"],
                }
            ],
        }
    ],
    "metrics": [
        {
            "name": "latest_left_yoy_percent",
            "value": round(latest_left, 2),
            "unit": "percent",
            "source_series": [left_id],
        },
        {
            "name": "latest_right_yoy_percent",
            "value": round(latest_right, 2),
            "unit": "percent",
            "source_series": [right_id],
        },
        {
            "name": "latest_inflation_gap_percent",
            "value": round(latest_gap, 2),
            "unit": "percentage points",
            "source_series": list(series_ids),
        },
        {
            "name": "five_year_average_gap_percent",
            "value": round(avg_gap, 2),
            "unit": "percentage points",
            "source_series": list(series_ids),
        },
        {
            "name": "overlap_periods",
            "value": len(yoy_rows),
            "unit": "periods",
            "source_series": list(series_ids),
        },
    ],
    "claims": [
        {
            "text": (
                series_name(left_id, "growth")
                + " is currently "
                + direction
                + " "
                + series_name(right_id, "growth")
                + "."
            ),
            "metric_refs": ["latest_inflation_gap_percent"],
        }
    ],
    "charts": [
        {
            "type": brief_type if brief_type in {"line", "scatter", "bars", "panels"} else "line",
            "layout": "single",
            "shared_y_axis": True,
            "title": title,
            "x_field": "date",
            "y_field": [left_field, right_field],
            "unit": "percent",
            "y_label": "year-over-year percent",
            "series_id": ",".join(series_ids),
            "series_ids": list(series_ids),
            "y_starts_at_zero": brief_y0,
            "legend": {
                left_field: series_name(left_id, "growth"),
                right_field: series_name(right_id, "growth"),
            },
            "data": yoy_rows,
            "notes": notes,
        }
    ],
    "method_notes": (
        "Aligned overlapping dates, then computed year-over-year percent changes "
        "and the gap (first series minus second). Index bases differ, so raw levels "
        "are not compared on one axis."
    ),
    "warnings": [
        "CPI and PCE use different baskets and index bases; the gap is not a forecast.",
        "The latest year-over-year reading may use a partial month.",
    ],
}
"""


def comparison_draft(analysis: AnalysisArtifact) -> DraftArtifact:
    metrics_by_name = _metrics_by_name(analysis)
    left_yoy = metrics_by_name.get("latest_left_yoy_percent", {})
    right_yoy = metrics_by_name.get("latest_right_yoy_percent", {})
    gap = metrics_by_name.get("latest_inflation_gap_percent", {})
    avg_gap = metrics_by_name.get("five_year_average_gap_percent", {})
    overlap = metrics_by_name.get("overlap_periods", {})
    source_series = [
        str(item)
        for item in gap.get("source_series") or []
        if item
    ]
    if len(source_series) < 2:
        source_series = [
            str(metric.get("source_series", [""])[0])
            for metric in analysis.metrics
            if isinstance(metric, dict) and metric.get("source_series")
        ]
        source_series = [item for item in dict.fromkeys(source_series) if item]
    left, right = (source_series + ["CPIAUCSL", "PCEPI"])[:2]
    left_name = plain_series_name(left)
    right_name = plain_series_name(right)
    gap_value = gap.get("value")
    if isinstance(gap_value, (int, float)):
        rounded_gap = round(float(gap_value), 2)
        direction = "above" if rounded_gap > 0 else "below" if rounded_gap < 0 else "in line with"
        abs_gap = abs(rounded_gap)
        lead = (
            f"The latest {result_phrase(left)} reading is about {abs_gap} percentage "
            f"points {direction} {result_phrase(right)} "
            f"({left_yoy.get('value')}% vs {right_yoy.get('value')}%)."
        )
    else:
        lead = (
            f"{result_phrase(left)} and {result_phrase(right)} were compared using "
            "year-over-year percent changes."
        )
    avg_bit = ""
    if isinstance(avg_gap.get("value"), (int, float)):
        avg_bit = (
            f" Over the overlapping window the average gap was about "
            f"{round(float(avg_gap['value']), 2)} percentage points."
        )
    overlap_n = overlap.get("value")
    overlap_bit = (
        f" over {overlap_n} overlapping periods" if overlap_n is not None else ""
    )
    answer = (
        f"{lead}{avg_bit}\n\n"
        f"{_sentence_name(left_name)} ({left}) and {right_name} ({right}) "
        "are the FRED series used here.\n\n"
        f"The comparison uses year-over-year percent changes{overlap_bit}. "
        "Different index bases mean raw levels are not compared directly."
    )
    return DraftArtifact(
        answer=answer,
        referenced_metrics=[
            name
            for name in (
                "latest_inflation_gap_percent",
                "latest_left_yoy_percent",
                "latest_right_yoy_percent",
                "five_year_average_gap_percent",
                "overlap_periods",
            )
            if name in metrics_by_name
        ],
        chart_paths=_chart_paths(analysis),
    )


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
    left_name = plain_series_name(left)
    right_name = plain_series_name(right)
    left_result = result_phrase(left)
    right_result = result_phrase(right)
    value = correlation.get("value")
    if isinstance(value, (int, float)):
        rounded = round(float(value), 2)
        if value < -0.15:
            lead = (
                f"Over this window, {left_result} and {right_result} moved opposite "
                f"each other; the correlation is about {rounded}."
            )
        elif value > 0.15:
            lead = (
                f"Over this window, {left_result} and {right_result} moved together; "
                f"the correlation is about {rounded}."
            )
        else:
            lead = (
                f"Over this window, {left_result} and {right_result} showed little "
                f"relationship; the correlation is about {rounded}."
            )
    else:
        lead = (
            f"Over this window, {left_result} and {right_result} were compared "
            "using aligned percent changes."
        )
    overlap_n = overlap.get("value")
    overlap_bit = (
        f"over {overlap_n} overlapping periods"
        if overlap_n is not None
        else "over the overlapping periods"
    )
    series_sentence = (
        f"{_sentence_name(left_name)} ({left}) and {right_name} ({right}) "
        "are the FRED series used here."
    )
    answer = (
        f"{lead}\n\n"
        f"{series_sentence}\n\n"
        f"The estimate uses aligned period-over-period growth {overlap_bit}. "
        "It is not causal and is not a full lead-lag study."
    )
    return DraftArtifact(
        answer=answer,
        referenced_metrics=[
            name
            for name in ("growth_correlation", "overlap_periods", "latest_left_value", "latest_right_value")
            if name in metrics_by_name
        ],
        chart_paths=_chart_paths(analysis),
    )


def looks_like_jargony_relationship_draft(draft: Any) -> bool:
    text = _draft_answer_text(draft).lower()
    if not text:
        return True
    return any(
        phrase in text
        for phrase in (
            "contemporaneous association",
            "contemporaneously associated",
            "does not by itself identify lead-lag",
            "period-over-period growth in cpiaucsl",
        )
    )


def draft_uses_plain_series_names(draft: Any, analysis: AnalysisArtifact | None = None) -> bool:
    text = _draft_answer_text(draft).lower()
    series_ids: list[str] = []
    if analysis is not None:
        for metric in analysis.metrics:
            if not isinstance(metric, dict):
                continue
            for series_id in metric.get("source_series") or []:
                if isinstance(series_id, str) and series_id not in series_ids:
                    series_ids.append(series_id)
    if not series_ids:
        series_ids = ["CPIAUCSL", "GDPC1"]
    for series_id in series_ids:
        aliases = series_name_aliases(series_id)
        if not aliases:
            continue
        if not any(alias in text for alias in aliases):
            return False
    return True


def looks_like_canned_cpi_draft(draft: Any) -> bool:
    text = _draft_answer_text(draft).lower()
    return (
        "has left the cpi index materially higher" in text
        or "the cpiaucsl index increased by" in text
    ) and "correlation" not in text


def _draft_answer_text(draft: Any) -> str:
    if hasattr(draft, "answer"):
        return str(draft.answer)
    if isinstance(draft, dict):
        return str(draft.get("answer") or "")
    return ""


def _sentence_name(name: str) -> str:
    if not name:
        return name
    if name[:1].islower():
        return name[0].upper() + name[1:]
    return name


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
