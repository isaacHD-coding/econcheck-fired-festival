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
from workers.openai_checker import OpenAIChecker
from workers.openai_worker import OpenAIWorker


DEFAULT_RUNS_DIR = Path("runs")
MOCK_MODE = "Mock demo"
OPENAI_MODE = "OpenAI agent"


def run_question(
    question: str,
    runs_dir: str | Path = DEFAULT_RUNS_DIR,
    fred_api_key: str | None = None,
    openai_api_key: str | None = None,
    worker_mode: str = MOCK_MODE,
) -> str:
    run_id = f"run-{uuid4().hex[:8]}"
    state = RunState(
        run_id=run_id,
        question=question,
        current_stage=Stage.INPUT,
        retry_count=0,
    )
    worker, checker = _worker_pair(worker_mode, openai_api_key)
    Orchestrator(
        state,
        runs_dir=runs_dir,
        worker=worker,
        checker=checker,
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
    worker_mode = st.selectbox("Worker mode", [MOCK_MODE, OPENAI_MODE])
    fred_api_key = st.text_input("FRED API key", type="password")
    openai_api_key = st.text_input("OpenAI API key", type="password")

    has_fred_api_key = bool(_clean_api_key(fred_api_key) or os.environ.get("FRED_API_KEY"))
    needs_openai_api_key = worker_mode == OPENAI_MODE
    has_openai_api_key = bool(
        _clean_api_key(openai_api_key) or os.environ.get("OPENAI_API_KEY")
    )
    if not has_fred_api_key:
        st.warning("Enter a FRED API key to run the live CPI analysis.")
    if needs_openai_api_key and not has_openai_api_key:
        st.warning("Enter an OpenAI API key to run the model-backed agent.")

    can_run = bool(
        question.strip()
        and has_fred_api_key
        and (not needs_openai_api_key or has_openai_api_key)
    )
    if st.button("Run", disabled=not can_run):
        with st.status("Running harness", expanded=True):
            run_id = run_question(
                question,
                fred_api_key=fred_api_key,
                openai_api_key=openai_api_key,
                worker_mode=worker_mode,
            )
            st.write(f"Run ID: {run_id}")

        view = load_run_view(run_id)
        final_answer = view["artifacts"].get("final_answer.json")
        if isinstance(final_answer, dict):
            st.subheader("Answer")
            st.write(final_answer.get("answer", "No answer released."))


def _worker_pair(worker_mode: str, openai_api_key: str | None):
    if _is_openai_mode(worker_mode):
        key = _clean_api_key(openai_api_key)
        return OpenAIWorker(api_key=key), OpenAIChecker(api_key=key)
    return MockWorker(), MockChecker()


def _is_openai_mode(worker_mode: str) -> bool:
    return worker_mode.strip().lower() in {"openai", OPENAI_MODE.lower()}


def _clean_api_key(fred_api_key: str | None) -> str | None:
    if fred_api_key is None:
        return None
    cleaned = fred_api_key.strip()
    return cleaned or None


if __name__ == "__main__":
    main()
