from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import streamlit as st

from app.observability import load_run_view
from harness.orchestrator import Orchestrator
from harness.state import RunState, Stage
from workers.mock_checker import MockChecker
from workers.mock_worker import MockWorker


DEFAULT_RUNS_DIR = Path("runs")


def run_question(
    question: str,
    runs_dir: str | Path = DEFAULT_RUNS_DIR,
    fred_api_key: str | None = None,
) -> str:
    run_id = f"run-{uuid4().hex[:8]}"
    state = RunState(
        run_id=run_id,
        question=question,
        current_stage=Stage.INPUT,
        retry_count=0,
    )
    Orchestrator(
        state,
        runs_dir=runs_dir,
        worker=MockWorker(),
        checker=MockChecker(),
        fred_api_key=_clean_api_key(fred_api_key),
    ).run()
    return run_id


def main() -> None:
    st.set_page_config(page_title="EconCheck", layout="wide")
    st.title("EconCheck")

    question = st.text_input(
        "Question",
        "What has happened to CPI inflation over the last five years?",
    )
    fred_api_key = st.text_input("FRED API key", type="password")
    has_api_key = bool(_clean_api_key(fred_api_key) or os.environ.get("FRED_API_KEY"))
    if not has_api_key:
        st.warning("Enter a FRED API key to run the live CPI analysis.")

    if st.button("Run", disabled=not question.strip() or not has_api_key):
        with st.status("Running harness", expanded=True):
            run_id = run_question(question, fred_api_key=fred_api_key)
            st.write(f"Run ID: {run_id}")

        view = load_run_view(run_id)
        final_answer = view["artifacts"].get("final_answer.json")
        if isinstance(final_answer, dict):
            st.subheader("Answer")
            st.write(final_answer.get("answer", "No answer released."))


def _clean_api_key(fred_api_key: str | None) -> str | None:
    if fred_api_key is None:
        return None
    cleaned = fred_api_key.strip()
    return cleaned or None


if __name__ == "__main__":
    main()
