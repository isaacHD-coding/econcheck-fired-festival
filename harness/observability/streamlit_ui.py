"""Shared Streamlit rendering helpers for EconCheck observability."""

from __future__ import annotations

from typing import Any

from harness.observability.loader import RunArtifacts
from harness.observability.view_models import (
    analysis_summary,
    answer_text,
    artifact_for_stage,
    chart_specs,
    planner_summary,
    progress_stages,
    selected_series,
)


def render_progress(st: Any, run: RunArtifacts) -> None:
    stages = progress_stages(run)
    columns = st.columns(len(stages))

    for column, stage in zip(columns, stages):
        column.markdown(f"**{stage['icon']} {stage['label']}**")
        column.caption(stage["summary"])


def render_answer(st: Any, run: RunArtifacts) -> None:
    st.write(answer_text(run))
    referenced_metrics = run.draft.get("referenced_metrics", [])
    if referenced_metrics:
        st.caption("Referenced metrics: " + ", ".join(referenced_metrics))


def render_chart(st: Any, run: RunArtifacts) -> None:
    charts = chart_specs(run)
    if not charts:
        st.info("No chart artifact is available for this run.")
        return

    chart = charts[0]
    st.markdown(f"**{chart.get('title', 'Chart')}**")
    data = chart.get("data", [])
    if data:
        st.line_chart(
            data,
            x=chart.get("x", "date"),
            y=chart.get("y", "value"),
            width="stretch",
        )
    with st.expander("Chart artifact JSON"):
        st.json(chart)


def render_timeline_selector(st: Any, run: RunArtifacts) -> str:
    stages = progress_stages(run)
    stage_ids = [stage["stage_id"] for stage in stages]
    labels = {
        stage["stage_id"]: f"{stage['icon']} {stage['label']}" for stage in stages
    }
    return st.radio(
        "Run Timeline",
        options=stage_ids,
        format_func=lambda stage_id: labels[stage_id],
        horizontal=True,
    )


def render_stage_artifact(st: Any, run: RunArtifacts, stage_id: str) -> None:
    artifact = artifact_for_stage(run, stage_id)
    stage_label = next(
        stage["label"] for stage in progress_stages(run) if stage["stage_id"] == stage_id
    )
    st.subheader(stage_label)

    if stage_id == "planning":
        render_planner(st, run.planner)
    elif stage_id == "data_discovery":
        render_selected_data(st, run)
    elif stage_id == "code_generation":
        render_generated_code(st, run.code)
    elif stage_id == "draft_answer":
        render_analysis(st, run.analysis)
    elif stage_id == "release":
        render_answer(st, run)
    else:
        render_status_list(st, artifact)

    with st.expander("Raw artifact JSON"):
        st.json(artifact)


def render_status_list(st: Any, items: list[dict[str, Any]]) -> None:
    if not items:
        st.write("No items recorded.")
        return

    for item in items:
        status, name = status_item_label(item)
        st.markdown(f"**{status}** {name}")
        st.caption(item.get("message", ""))


def status_item_label(item: dict[str, Any]) -> tuple[str, str]:
    status = str(item.get("status") or item.get("severity") or "unknown").upper()
    name = str(item.get("name") or item.get("type") or item.get("stage") or "artifact")
    return status, name


def render_planner(st: Any, planner: dict[str, Any]) -> None:
    summary = planner_summary(planner)
    st.markdown(f"**Question type:** {summary['question_type']}")
    st.markdown(f"**Measurement strategy:** {summary['measurement_strategy']}")
    st.markdown("**Economic concepts**")
    render_bullets(st, summary["economic_concepts"])
    st.markdown("**Information requirements**")
    render_bullets(st, summary["information_requirements"])
    st.markdown("**Search queries**")
    render_bullets(st, summary["search_queries"])
    st.markdown("**Required outputs**")
    render_bullets(st, summary["required_outputs"])
    st.markdown("**Success criteria**")
    render_bullets(st, summary["success_criteria"])


def render_selected_data(st: Any, run: RunArtifacts) -> None:
    st.markdown("**Selected series**")
    st.table(selected_series(run))
    rejected = run.data_selection.get("rejected_series", [])
    if rejected:
        st.markdown("**Rejected series**")
        st.table(rejected)
    st.markdown("**Justification**")
    st.write(run.data_selection.get("justification", ""))


def render_generated_code(st: Any, code: dict[str, Any]) -> None:
    st.code(str(code.get("code", "")), language="python")


def render_analysis(st: Any, analysis: dict[str, Any]) -> None:
    summary = analysis_summary(analysis)
    st.markdown("**Metrics**")
    st.table(summary["metrics"])
    st.markdown("**Claims**")
    st.table(summary["claims"])
    st.markdown("**Charts**")
    st.table(
        [
            {
                "title": chart.get("title", ""),
                "type": chart.get("type", ""),
                "unit": chart.get("unit", ""),
            }
            for chart in summary["charts"]
        ]
    )
    st.markdown("**Warnings**")
    render_bullets(st, summary["warnings"] or ["No analysis warnings."])
    st.markdown("**Method notes**")
    st.write(summary["method_notes"])


def render_bullets(st: Any, items: list[Any]) -> None:
    for item in items:
        st.markdown(f"- {item}")


def render_raw_json(st: Any, label: str, value: Any) -> None:
    with st.expander(label):
        st.json(value)
