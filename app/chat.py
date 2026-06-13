from __future__ import annotations

import os
from pathlib import Path
import sys
from uuid import uuid4

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from .observability import load_run_view
except ImportError:
    from observability import load_run_view

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
    st.caption("Harness-aware economic analysis")

    with st.sidebar:
        st.header("Run configuration")
        worker_mode = st.selectbox("Worker mode", [MOCK_MODE, OPENAI_MODE])
        fred_api_key = st.text_input("FRED API key", type="password")
        openai_api_key = ""
        if worker_mode == OPENAI_MODE:
            openai_api_key = st.text_input("OpenAI API key", type="password")

    st.header("Question Input")
    question = st.text_area(
        "Question",
        value="What has happened to CPI inflation over the last five years?",
        height=96,
    )

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
    if st.button("Run through harness", disabled=not can_run):
        with st.status("Running harness", expanded=True):
            run_id = run_question(
                question,
                fred_api_key=fred_api_key,
                openai_api_key=openai_api_key,
                worker_mode=worker_mode,
            )
            st.write(f"Run ID: {run_id}")
            st.session_state.current_run_id = run_id

    run_id = st.session_state.get("current_run_id")
    if not run_id:
        return

    view = load_run_view(run_id)

    st.header("Harness Progress")
    _render_progress(view)

    answer_column, chart_column = st.columns([3, 2])
    with answer_column:
        st.header("Answer")
        _render_answer(view)

    with chart_column:
        st.header("Chart")
        _render_chart(view)

    with st.expander("Run artifacts"):
        st.write(f"Run ID: {run_id}")
        st.json(view.get("state") or {})


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


def _render_progress(view: dict) -> None:
    artifacts = view.get("artifacts", {})
    stages = [
        ("Input", "input.json"),
        ("Plan", "plan.json"),
        ("FRED", "fred_search.json"),
        ("Data", "data.json"),
        ("Code", "analysis.json"),
        ("Checker", "checker.json"),
        ("Release", "final_answer.json"),
    ]
    columns = st.columns(len(stages))
    for column, (label, artifact_name) in zip(columns, stages):
        available = artifact_name in artifacts
        column.markdown(f"**{label}**")
        column.caption("Complete" if available else "Pending")


def _render_answer(view: dict) -> None:
    final_answer = view["artifacts"].get("final_answer.json")
    if not isinstance(final_answer, dict):
        st.info("No released answer is available yet.")
        return

    st.write(final_answer.get("answer", "No answer released."))
    referenced_metrics = final_answer.get("referenced_metrics", [])
    if referenced_metrics:
        st.caption("Referenced metrics: " + ", ".join(referenced_metrics))


def _render_chart(view: dict) -> None:
    analysis = view["artifacts"].get("analysis.json")
    if not isinstance(analysis, dict):
        st.info("No analysis artifact is available yet.")
        return

    charts = analysis.get("charts", [])
    if not charts:
        st.info("No chart artifact is available for this run.")
        return

    chart = charts[0]
    if not isinstance(chart, dict):
        st.json(chart)
        return

    st.markdown(f"**{chart.get('title', 'Chart')}**")
    data = chart.get("data", [])
    if data:
        st.line_chart(
            data,
            x=chart.get("x_field", chart.get("x", "date")),
            y=chart.get("y_field", chart.get("y", "value")),
            width="stretch",
        )
    with st.expander("Chart artifact JSON"):
        st.json(chart)


if __name__ == "__main__":
    main()
