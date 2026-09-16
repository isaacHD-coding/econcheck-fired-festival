"""Structured chart briefs and adaptive chart-design advice."""

from __future__ import annotations

from typing import Any

from harness.domain import is_canonical_cpi_demo_question, is_relationship_question, plan_requests_relationship
from workers.artifacts import ChartBriefArtifact, DataArtifact, PlannerArtifact


CHART_DESIGN_ADVICE = """
Adaptive chart design (follow before drawing):
- Match the visual to the claim. Correlation or comovement → comparable transforms
  (growth, YoY, QoQ, MoM, z-score) on a shared axis. Levels questions → raw series.
  Rate questions → the rate series, not the underlying index.
- Choose transforms so series are comparable for that claim. Document mixed-frequency
  alignment (for example last-observation-carried-forward onto the lower-frequency
  dates) in notes. Never invent a FRED series that was not fetched.
- Scale honesty: do not dwarf a series. Use dual-axis, stacked / small-multiple
  panels, or a growth overlay when scales or units differ. Do not force y to start
  at 0 when that flattens a meaningful move, unless plotting bars of nonnegative levels.
- Choose a time window that fits the question; flag partial end periods in notes.
- Prefer a focal series; avoid clutter. Small multiples over spaghetti when many series.
- Provenance: cite FRED ids, units, and overlap n in notes when reporting correlation.
- Chart type must fit the claim (line for co-movement over time, scatter for pairwise
  association, bars for discrete nonnegative levels, panels for small multiples).
- Title and legend in plain English (for example "CPI growth", "Real GDP growth"),
  not raw variable names like CPIAUCSL_growth.
- User-facing chart notes/captions must be a short plain explanation of what is
  plotted: units, alignment, and sample size n. Never put harness design rules
  or sentences that start with "Do not…" in chart notes, titles, or legends.
  Put those rules in design_notes for observability only.
""".strip()

INSTRUCTION_NOTE_PHRASES = (
    "do not place incompatible",
    "do not force y",
    "if a levels companion",
    "use dual-axis or stacked",
    "follow the chart brief",
    "never invent",
    "codegen must",
    "shared y-axis",
    "plot comparable growth rates on one percent",
    "report overlap n with any correlation",
)

SERIES_LABELS = {
    "CPIAUCSL": {
        "name": "CPI all items",
        "growth": "CPI growth",
        "level": "CPI all items",
        "aliases": ("cpi all", "consumer price", "inflation", "headline cpi"),
        "result": "inflation",
    },
    "GDPC1": {
        "name": "real GDP",
        "growth": "Real GDP growth",
        "level": "Real GDP",
        "aliases": ("real gdp", "gross domestic"),
        "result": "real GDP growth",
    },
    "UNRATE": {
        "name": "unemployment rate",
        "growth": "Unemployment rate change",
        "level": "Unemployment rate",
        "aliases": ("unemployment",),
        "result": "the unemployment rate",
    },
}

ALLOWED_LAYOUTS = {"single", "dual_axis", "stacked"}
ALLOWED_CHART_TYPES = {"line", "scatter", "bars", "panels"}
COMPARABLE_TRANSFORMS = {
    "growth",
    "yoy",
    "qoq",
    "mom",
    "zscore",
    "z-score",
    "index_to_100",
    "index-to-100",
    "percent_change",
    "percent",
}


def build_chart_brief(
    plan: PlannerArtifact | None,
    data: DataArtifact | dict[str, Any] | None,
    *,
    question: str = "",
) -> ChartBriefArtifact:
    """Harness/worker fallback brief using only fetched series ids."""

    series_ids = _series_ids(data)
    units_by_id = _units_by_series(data)
    relationship = _is_relationship(plan, data, question)
    if relationship and len(series_ids) >= 2:
        return _relationship_brief(series_ids, units_by_id, question=question)
    if series_ids and (
        is_canonical_cpi_demo_question(question) or series_ids == ["CPIAUCSL"]
    ):
        return _cpi_brief(series_ids[0], units_by_id.get(series_ids[0], "index 1982-1984=100"))
    if series_ids:
        return _single_series_brief(series_ids[0], units_by_id.get(series_ids[0], "source units"))
    return ChartBriefArtifact(
        claim="No fetched series are available to chart.",
        series_ids=[],
        transforms=["levels"],
        layout="single",
        y_starts_at_zero=False,
        time_window_rationale="No observations were fetched.",
        annotations=["Recession shading omitted; no NBER series was fetched."],
        title="No series available",
        x_label="date",
        y_label="value",
        units="source units",
        notes="Chart brief could not name a FRED series without inventing one.",
        chart_type="line",
    )


def repair_chart_brief(
    brief: ChartBriefArtifact | dict[str, Any],
    plan: PlannerArtifact | None,
    data: DataArtifact | dict[str, Any] | None,
    *,
    question: str = "",
) -> ChartBriefArtifact:
    """Keep worker-chosen design when valid; never keep invented series ids."""

    fallback = build_chart_brief(plan, data, question=question)
    try:
        artifact = (
            brief
            if isinstance(brief, ChartBriefArtifact)
            else ChartBriefArtifact.from_dict(brief)
        )
    except (TypeError, ValueError):
        return fallback

    fetched = _series_ids(data)
    fetched_set = set(fetched)
    kept = [series_id for series_id in artifact.series_ids if series_id in fetched_set]
    if fetched and not kept:
        return fallback
    if len(fetched) >= 2 and len(kept) < 2:
        return fallback
    if not fetched and artifact.series_ids:
        return fallback

    payload = artifact.to_dict()
    payload["series_ids"] = kept or fallback.series_ids
    payload["layout"] = _normalize_layout(payload.get("layout"))
    payload["chart_type"] = _normalize_chart_type(payload.get("chart_type"))
    if not payload.get("transforms"):
        payload["transforms"] = list(fallback.transforms)
    if not str(payload.get("claim") or "").strip():
        payload["claim"] = fallback.claim
    if not str(payload.get("title") or "").strip():
        payload["title"] = fallback.title
    if not str(payload.get("units") or "").strip():
        payload["units"] = fallback.units
    if not str(payload.get("y_label") or "").strip():
        payload["y_label"] = fallback.y_label
    if not str(payload.get("x_label") or "").strip():
        payload["x_label"] = fallback.x_label
    if not str(payload.get("notes") or "").strip():
        payload["notes"] = fallback.notes
    payload["notes"], payload["design_notes"] = _split_user_and_design_notes(
        payload.get("notes") or "",
        payload.get("design_notes") or "",
        fallback.notes,
        fallback.design_notes,
    )
    if not str(payload.get("time_window_rationale") or "").strip():
        payload["time_window_rationale"] = fallback.time_window_rationale
    if not isinstance(payload.get("annotations"), list):
        payload["annotations"] = list(fallback.annotations)
    if not isinstance(payload.get("y_starts_at_zero"), bool):
        payload["y_starts_at_zero"] = fallback.y_starts_at_zero
    try:
        return ChartBriefArtifact.from_dict(payload)
    except (TypeError, ValueError):
        return fallback


def _relationship_brief(
    series_ids: list[str],
    units_by_id: dict[str, str],
    *,
    question: str,
) -> ChartBriefArtifact:
    left, right = series_ids[0], series_ids[1]
    units_note = "; ".join(
        f"{series_id} native units: {units_by_id.get(series_id, 'source units')}"
        for series_id in series_ids[:2]
    )
    title_left = plain_series_name(left)
    title_right = plain_series_name(right)
    return ChartBriefArtifact(
        claim=(
            f"{title_left} growth and {title_right} growth moved together or "
            f"opposite each other over the overlapping window."
        ),
        series_ids=list(series_ids),
        transforms=["growth"],
        layout="single",
        y_starts_at_zero=False,
        time_window_rationale=(
            "Use the overlapping fetched window that can support the claimed "
            "relationship. Flag a partial final period in notes when the last "
            "observation is not a complete month or quarter."
        ),
        annotations=[
            "Recession shading omitted because no NBER recession series was fetched."
        ],
        title=f"{growth_legend_label(left)} vs {growth_legend_label(right)}",
        x_label="date",
        y_label="percent change",
        units="percent",
        notes=(
            f"Percent change in {title_left} ({left}) and {title_right} ({right}) "
            "after aligning mixed frequencies."
        ),
        chart_type="line",
        y_left_label=growth_legend_label(left),
        y_right_label=growth_legend_label(right),
        design_notes=(
            f"Align mixed frequencies with last-observation-carried-forward onto the "
            f"lower-frequency dates, then plot comparable growth rates on one percent "
            f"axis. {units_note}. Report overlap n with any correlation. Do not place "
            "incompatible raw levels on one shared y-axis; if a levels companion is "
            "shown, use dual-axis or stacked panels."
        ),
    )


def _cpi_brief(series_id: str, units: str) -> ChartBriefArtifact:
    return ChartBriefArtifact(
        claim="Headline CPI (CPIAUCSL) changed over the last five years.",
        series_ids=[series_id],
        transforms=["levels"],
        layout="single",
        y_starts_at_zero=False,
        time_window_rationale=(
            "Fetched five-year CPI window. A partial latest month should be noted "
            "rather than dropped silently."
        ),
        annotations=[
            "Recession shading omitted because no NBER recession series was fetched."
        ],
        title="CPI all items (CPIAUCSL) over the last five years",
        x_label="date",
        y_label=f"CPI index ({units})",
        units=units,
        notes=f"CPI all-items index over the last five years ({units}).",
        chart_type="line",
        design_notes=(
            "Single-series levels chart. Do not force y=0; the index sits far from "
            "zero and a zero baseline would flatten the five-year move."
        ),
    )


def _single_series_brief(series_id: str, units: str) -> ChartBriefArtifact:
    label = plain_series_name(series_id)
    return ChartBriefArtifact(
        claim=f"{label} ({series_id}) changed over the fetched window.",
        series_ids=[series_id],
        transforms=["levels"],
        layout="single",
        y_starts_at_zero=False,
        time_window_rationale=(
            "Use the fetched window that answers the question. Flag a partial "
            "end period in notes."
        ),
        annotations=[
            "Recession shading omitted because no NBER recession series was fetched."
        ],
        title=f"{label} ({series_id}) over the fetched window",
        x_label="date",
        y_label=f"{label} ({units})",
        units=units,
        notes=f"{label} ({series_id}) over the fetched window, in {units}.",
        chart_type="line",
        design_notes=(
            f"Single-series levels chart of {series_id} in {units}. Do not force "
            "y=0 unless plotting nonnegative bars."
        ),
    )


def _is_relationship(
    plan: PlannerArtifact | None,
    data: DataArtifact | dict[str, Any] | None,
    question: str,
) -> bool:
    if is_relationship_question(question) or plan_requests_relationship(plan):
        return True
    return len(_series_ids(data)) > 1


def _series_ids(data: DataArtifact | dict[str, Any] | None) -> list[str]:
    if data is None:
        return []
    if hasattr(data, "series_ids") and data.series_ids:
        return [str(item) for item in data.series_ids]
    if hasattr(data, "observations") and data.observations:
        return [str(item) for item in data.observations]
    if isinstance(data, dict):
        if data.get("series_ids"):
            return [str(item) for item in data["series_ids"]]
        if data.get("observations"):
            return [str(item) for item in data["observations"]]
    return []


def _units_by_series(data: DataArtifact | dict[str, Any] | None) -> dict[str, str]:
    metadata: dict[str, Any] = {}
    if data is None:
        return {}
    if hasattr(data, "metadata") and isinstance(data.metadata, dict):
        metadata = data.metadata
    elif isinstance(data, dict) and isinstance(data.get("metadata"), dict):
        metadata = data["metadata"]
    series_meta = metadata.get("series") or {}
    units: dict[str, str] = {}
    if isinstance(series_meta, dict):
        for series_id, payload in series_meta.items():
            if isinstance(payload, dict) and payload.get("units"):
                units[str(series_id)] = str(payload["units"])
            elif isinstance(payload, str) and payload:
                units[str(series_id)] = payload
    selected = metadata.get("selected_series") or []
    if isinstance(selected, list):
        for item in selected:
            if not isinstance(item, dict):
                continue
            series_id = item.get("series_id")
            if series_id and item.get("units") and str(series_id) not in units:
                units[str(series_id)] = str(item["units"])
    return units


def plain_series_name(series_id: str) -> str:
    info = SERIES_LABELS.get(series_id)
    if info:
        return str(info["name"])
    return series_id


def growth_legend_label(series_id: str) -> str:
    info = SERIES_LABELS.get(series_id)
    if info:
        return str(info["growth"])
    return f"{series_id} growth"


def level_legend_label(series_id: str) -> str:
    info = SERIES_LABELS.get(series_id)
    if info:
        return str(info["level"])
    return series_id


def series_name_aliases(series_id: str) -> tuple[str, ...]:
    info = SERIES_LABELS.get(series_id)
    if info:
        return tuple(info["aliases"])
    return ()


def result_phrase(series_id: str) -> str:
    info = SERIES_LABELS.get(series_id)
    if info and info.get("result"):
        return str(info["result"])
    return f"{plain_series_name(series_id)} growth"


def is_instruction_note(text: str) -> bool:
    blob = " ".join(str(text or "").lower().split())
    if not blob:
        return False
    if blob.startswith("do not "):
        return True
    return any(phrase in blob for phrase in INSTRUCTION_NOTE_PHRASES)


def user_facing_chart_notes(text: str, *, fallback: str = "") -> str:
    if text and not is_instruction_note(text):
        return str(text).strip()
    return (fallback or "").strip()


def humanize_field_name(field: str) -> str:
    raw = str(field or "").strip()
    if raw.lower().endswith("_growth"):
        return growth_legend_label(raw[: -len("_growth")])
    return level_legend_label(raw)


def _split_user_and_design_notes(
    notes: str,
    design_notes: str,
    fallback_notes: str,
    fallback_design: str,
) -> tuple[str, str]:
    user = user_facing_chart_notes(notes, fallback=fallback_notes)
    if is_instruction_note(user):
        user = "Percent change after aligning mixed frequencies."
    design = str(design_notes or "").strip()
    if is_instruction_note(notes) and not design:
        design = str(notes).strip()
    if not design:
        design = str(fallback_design or "").strip()
    return user, design


def _normalize_layout(value: Any) -> str:
    text = str(value or "single").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "small_multiples": "stacked",
        "small_multiple": "stacked",
        "panels": "stacked",
        "panel": "stacked",
        "dual": "dual_axis",
        "growth_overlay": "single",
    }
    text = aliases.get(text, text)
    return text if text in ALLOWED_LAYOUTS else "single"


def _normalize_chart_type(value: Any) -> str:
    text = str(value or "line").strip().lower()
    aliases = {"bar": "bars", "scatterplot": "scatter", "panel": "panels"}
    text = aliases.get(text, text)
    return text if text in ALLOWED_CHART_TYPES else "line"
