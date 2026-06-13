"""Streamlit chat page for the EconCheck harness."""

from __future__ import annotations

import streamlit as st

from harness.observability import load_run_artifacts, run_question
from harness.observability.streamlit_ui import (
    render_answer,
    render_chart,
    render_progress,
)


DEFAULT_QUESTION = "What has happened to CPI inflation over the last five years?"


def main() -> None:
    st.set_page_config(page_title="EconCheck", layout="wide")
    st.title("EconCheck")
    st.caption("Harness-aware economic analysis")

    st.header("Question Input")
    question = st.text_area("Question", value=DEFAULT_QUESTION, height=96)
    submitted = st.button("Run through harness")

    if "current_run_id" not in st.session_state:
        st.session_state.current_run_id = run_question(DEFAULT_QUESTION)

    if submitted and question.strip():
        st.session_state.current_run_id = run_question(question)

    run = load_run_artifacts(st.session_state.current_run_id)

    st.header("Harness Progress")
    render_progress(st, run)

    answer_column, chart_column = st.columns([3, 2])
    with answer_column:
        st.header("Answer")
        render_answer(st, run)

    with chart_column:
        st.header("Chart")
        render_chart(st, run)


if __name__ == "__main__":
    main()
