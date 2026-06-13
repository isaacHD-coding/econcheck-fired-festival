"""Streamlit observability page for the EconCheck harness."""

from __future__ import annotations

import streamlit as st

from harness.observability import load_run_artifacts
from harness.observability.streamlit_ui import (
    render_analysis,
    render_answer,
    render_chart,
    render_generated_code,
    render_planner,
    render_raw_json,
    render_selected_data,
    render_stage_artifact,
    render_status_list,
    render_timeline_selector,
)


CURRENT_RUN_ID = "sample_cpi_run"


def main() -> None:
    st.set_page_config(page_title="EconCheck Observability", layout="wide")
    run = load_run_artifacts(CURRENT_RUN_ID)

    st.title("EconCheck Observability")
    st.caption(f"Current run: {run.run_id} ({run.source})")

    st.header("Run Timeline")
    selected_stage = render_timeline_selector(st, run)
    render_stage_artifact(st, run, selected_stage)

    st.divider()
    st.header("Guardrails")
    render_status_list(st, run.guardrails)
    render_raw_json(st, "Guardrails raw JSON", run.guardrails)

    st.header("Checkpoints")
    render_status_list(st, run.checkpoints)
    render_raw_json(st, "Checkpoints raw JSON", run.checkpoints)

    st.header("Alarms")
    render_status_list(st, run.alarms)
    render_raw_json(st, "Alarms raw JSON", run.alarms)

    st.header("Planner Output")
    render_planner(st, run.planner)
    render_raw_json(st, "Planner raw JSON", run.planner)

    st.header("Selected Data")
    render_selected_data(st, run)
    render_raw_json(st, "FRED search raw JSON", run.search)
    render_raw_json(st, "Selected data raw JSON", run.data_selection)

    st.header("Generated Code")
    render_generated_code(st, run.code)
    render_raw_json(st, "Generated code raw JSON", run.code)

    st.header("Analysis Output")
    render_analysis(st, run.analysis)
    render_chart(st, run)
    render_raw_json(st, "Analysis raw JSON", run.analysis)

    st.header("Final Answer")
    render_answer(st, run)
    render_raw_json(st, "Final answer raw JSON", run.draft)


if __name__ == "__main__":
    main()
