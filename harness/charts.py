"""Chart layout helpers for mixed-scale FRED series."""

from __future__ import annotations

from typing import Any

from workers.artifacts import AnalysisArtifact, ChartBriefArtifact


SCALE_RATIO_THRESHOLD = 10.0
GROWTH_HINTS = ("growth", "percent", "pct", "%", "yoy", "change")


def y_fields(chart: dict[str, Any]) -> list[str]:
    raw = chart.get("y_field", chart.get("y"))
    if raw is None:
        left = chart.get("y_left")
        right = chart.get("y_right")
        fields = [item for item in (left, right) if isinstance(item, str) and item]
        if fields:
            return fields
        return ["value"]
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    return ["value"]


def series_amplitudes(chart: dict[str, Any]) -> dict[str, float]:
    data = chart.get("data") or []
    amplitudes: dict[str, float] = {}
    for field in y_fields(chart):
        values = [
            abs(float(row[field]))
            for row in data
            if isinstance(row, dict) and isinstance(row.get(field), (int, float))
        ]
        if values:
            amplitudes[field] = max(values)
    return amplitudes


def scales_incompatible(chart: dict[str, Any]) -> bool:
    amplitudes = [value for value in series_amplitudes(chart).values() if value > 0]
    if len(amplitudes) < 2:
        return False
    return max(amplitudes) / min(amplitudes) >= SCALE_RATIO_THRESHOLD


def uses_comparable_units(chart: dict[str, Any]) -> bool:
    blob = " ".join(
        [
            str(chart.get("unit") or ""),
            str(chart.get("y_label") or ""),
            str(chart.get("title") or ""),
            " ".join(y_fields(chart)),
        ]
    ).lower()
    return any(hint in blob for hint in GROWTH_HINTS)


def shares_single_axis(chart: dict[str, Any]) -> bool:
    layout = _layout_name(chart)
    if layout in {"dual_axis", "stacked", "panels"}:
        return False
    if chart.get("shared_y_axis") is False:
        return False
    return len(y_fields(chart)) >= 2


def would_dwarf_a_series(chart: dict[str, Any]) -> bool:
    return shares_single_axis(chart) and scales_incompatible(chart) and not uses_comparable_units(chart)


def normalize_chart(
    chart: dict[str, Any],
    brief: ChartBriefArtifact | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rewrite mixed-scale single-axis overlays into a dual-axis or stacked descriptor."""

    normalized = apply_chart_brief(chart, brief)
    fields = y_fields(normalized)
    if len(fields) < 2:
        normalized.setdefault("layout", "single")
        normalized.setdefault("shared_y_axis", True)
        return normalized

    if uses_comparable_units(normalized) or not scales_incompatible(normalized):
        normalized.setdefault("layout", "single")
        normalized.setdefault("shared_y_axis", True)
        normalized["y_field"] = fields
        return normalized

    layout = _rewrite_layout(normalized, brief)
    normalized["layout"] = layout
    normalized["shared_y_axis"] = False
    normalized["y_field"] = fields
    normalized["y_left"] = normalized.get("y_left") or fields[0]
    normalized["y_right"] = normalized.get("y_right") or fields[1]
    if not normalized.get("y_left_label"):
        normalized["y_left_label"] = str(normalized["y_left"])
    if not normalized.get("y_right_label"):
        normalized["y_right_label"] = str(normalized["y_right"])
    return normalized


def apply_chart_brief(
    chart: dict[str, Any],
    brief: ChartBriefArtifact | dict[str, Any] | None,
) -> dict[str, Any]:
    payload = _brief_payload(brief)
    normalized = dict(chart)
    if not payload:
        return normalized
    if not normalized.get("title") and payload.get("title"):
        normalized["title"] = payload["title"]
    if not normalized.get("type") and payload.get("chart_type"):
        normalized["type"] = payload["chart_type"]
    if "y_starts_at_zero" not in normalized and "y_starts_at_zero" in payload:
        normalized["y_starts_at_zero"] = bool(payload["y_starts_at_zero"])
    if payload.get("notes") and not normalized.get("notes"):
        normalized["notes"] = payload["notes"]
    if payload.get("series_ids") and not normalized.get("series_id") and not normalized.get("series_ids"):
        series_ids = [str(item) for item in payload["series_ids"] if item]
        normalized["series_ids"] = series_ids
        normalized["series_id"] = ",".join(series_ids)
    if _chart_matches_brief_transform(normalized, payload):
        if not normalized.get("layout") and payload.get("layout"):
            normalized["layout"] = payload["layout"]
        if not normalized.get("unit") and not normalized.get("units") and payload.get("units"):
            normalized["unit"] = payload["units"]
        if not normalized.get("y_label") and payload.get("y_label"):
            normalized["y_label"] = payload["y_label"]
        if payload.get("y_left_label") and not normalized.get("y_left_label"):
            normalized["y_left_label"] = payload["y_left_label"]
        if payload.get("y_right_label") and not normalized.get("y_right_label"):
            normalized["y_right_label"] = payload["y_right_label"]
    return normalized


def normalize_analysis_charts(
    analysis: AnalysisArtifact,
    brief: ChartBriefArtifact | dict[str, Any] | None = None,
) -> AnalysisArtifact:
    analysis.charts = [
        normalize_chart(chart, brief) if isinstance(chart, dict) else chart
        for chart in analysis.charts
    ]
    return analysis


def render_charts(st: Any, charts: Any) -> None:
    if not isinstance(charts, list) or not charts:
        st.info("No chart artifact is available for this run.")
        return

    for index, chart in enumerate(charts):
        if not isinstance(chart, dict):
            st.json(chart)
            continue
        _render_one_chart(st, normalize_chart(chart), index=index)


def _render_one_chart(st: Any, chart: dict[str, Any], *, index: int) -> None:
    st.markdown(f"**{chart.get('title', f'Chart {index + 1}')}**")
    notes = chart.get("notes") or chart.get("method_notes")
    if notes:
        st.caption(str(notes))

    data = chart.get("data") or []
    if not data:
        with st.expander("Chart artifact JSON"):
            st.json(chart)
        return

    layout = _layout_name(chart)
    x_field = str(chart.get("x_field") or chart.get("x") or "date")
    fields = y_fields(chart)

    if layout == "dual_axis" and len(fields) >= 2:
        if not _render_dual_axis(st, chart, data, x_field, fields):
            _render_stacked(st, chart, data, x_field, fields)
    elif layout in {"stacked", "panels"} and len(fields) >= 2:
        _render_stacked(st, chart, data, x_field, fields)
    else:
        y = fields if len(fields) > 1 else fields[0]
        st.line_chart(data, x=x_field, y=y, width="stretch")

    with st.expander("Chart artifact JSON"):
        st.json(chart)


def _render_stacked(
    st: Any,
    chart: dict[str, Any],
    data: list[dict[str, Any]],
    x_field: str,
    fields: list[str],
) -> None:
    labels = {
        fields[0]: chart.get("y_left_label") or fields[0],
        fields[1]: chart.get("y_right_label") or fields[1],
    }
    for field in fields[:2]:
        st.caption(str(labels.get(field, field)))
        st.line_chart(data, x=x_field, y=field, width="stretch")


def _render_dual_axis(
    st: Any,
    chart: dict[str, Any],
    data: list[dict[str, Any]],
    x_field: str,
    fields: list[str],
) -> bool:
    try:
        import altair as alt
    except ImportError:
        return False

    left = str(chart.get("y_left") or fields[0])
    right = str(chart.get("y_right") or fields[1])
    left_title = str(chart.get("y_left_label") or left)
    right_title = str(chart.get("y_right_label") or right)
    zero = bool(chart.get("y_starts_at_zero"))
    base = alt.Chart(data).encode(x=alt.X(x_field, title=str(chart.get("x_label") or x_field)))
    left_layer = base.mark_line(color="#4C78A8").encode(
        y=alt.Y(left, axis=alt.Axis(title=left_title, titleColor="#4C78A8"), scale=alt.Scale(zero=zero)),
        tooltip=[x_field, left, right],
    )
    right_layer = base.mark_line(color="#F58518").encode(
        y=alt.Y(right, axis=alt.Axis(title=right_title, titleColor="#F58518"), scale=alt.Scale(zero=zero)),
        tooltip=[x_field, left, right],
    )
    layered = alt.layer(left_layer, right_layer).resolve_scale(y="independent")
    try:
        st.altair_chart(layered, width="stretch")
    except TypeError:
        st.altair_chart(layered)
    return True


def _layout_name(chart: dict[str, Any]) -> str:
    return str(chart.get("layout") or "single").lower().replace("-", "_").replace(" ", "_")


def _rewrite_layout(
    chart: dict[str, Any],
    brief: ChartBriefArtifact | dict[str, Any] | None,
) -> str:
    payload = _brief_payload(brief)
    requested = str((payload or {}).get("layout") or chart.get("layout") or "dual_axis")
    requested = requested.lower().replace("-", "_").replace(" ", "_")
    if requested in {"stacked", "panels", "small_multiples"}:
        return "stacked"
    return "dual_axis"


def _brief_payload(
    brief: ChartBriefArtifact | dict[str, Any] | None,
) -> dict[str, Any]:
    if brief is None:
        return {}
    if isinstance(brief, ChartBriefArtifact):
        return brief.to_dict()
    if hasattr(brief, "to_dict"):
        payload = brief.to_dict()
        return dict(payload) if isinstance(payload, dict) else {}
    if isinstance(brief, dict):
        return dict(brief)
    return {}


def _chart_matches_brief_transform(chart: dict[str, Any], payload: dict[str, Any]) -> bool:
    transforms = " ".join(str(item).lower() for item in (payload.get("transforms") or []))
    fields = " ".join(y_fields(chart)).lower()
    comparable = ("growth", "yoy", "qoq", "mom", "zscore", "percent", "index_to_100")
    brief_wants_comparable = any(token in transforms for token in comparable)
    fields_look_comparable = any(token in fields for token in comparable) or uses_comparable_units(chart)
    if brief_wants_comparable:
        return fields_look_comparable or not y_fields(chart)
    return True
