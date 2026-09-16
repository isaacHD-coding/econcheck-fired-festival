from __future__ import annotations

from pathlib import Path
import sys
from uuid import uuid4

import streamlit as st

from harness.config import load_env_files, resolve_fred_api_key, resolve_openai_api_key

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from .observability import list_run_ids, load_run_view
except ImportError:
    from observability import list_run_ids, load_run_view

from harness.orchestrator import Orchestrator
from harness.state import RunState, Stage
from workers.mock_checker import MockChecker
from workers.mock_worker import MockWorker
from workers.openai_checker import OpenAIChecker
from workers.openai_worker import OpenAIWorker


DEFAULT_RUNS_DIR = Path("runs")
MOCK_MODE = "Mock demo"
OPENAI_MODE = "OpenAI agent"
CANONICAL_QUESTION = "What has happened to CPI inflation over the last five years?"


def run_question(
    question: str,
    runs_dir: str | Path = DEFAULT_RUNS_DIR,
    fred_api_key: str | None = None,
    openai_api_key: str | None = None,
    worker_mode: str = MOCK_MODE,
) -> str:
    load_env_files()
    run_id = f"run-{uuid4().hex[:8]}"
    state = RunState(
        run_id=run_id,
        question=question,
        current_stage=Stage.INPUT,
        retry_count=0,
    )
    worker, checker = _worker_pair(worker_mode, openai_api_key)
    try:
        Orchestrator(
            state,
            runs_dir=runs_dir,
            worker=worker,
            checker=checker,
            fred_api_key=resolve_fred_api_key(fred_api_key),
        ).run()
    except Exception:
        # The orchestrator persists alarms/state before failing; the UI loads them.
        pass
    return run_id


def main() -> None:
    load_env_files()
    st.set_page_config(page_title="EconCheck", layout="wide")
    st.title("EconCheck")
    st.caption(
        "A governed harness for FRED economic questions. The worker proposes a plan; "
        "the harness searches FRED, fetches data, sandboxes analysis code, and decides "
        "whether an answer can be released."
    )

    with st.sidebar:
        st.header("Run configuration")
        worker_mode = st.selectbox("Worker mode", [MOCK_MODE, OPENAI_MODE])
        env_fred_key = resolve_fred_api_key()
        env_openai_key = resolve_openai_api_key()
        fred_api_key = st.text_input(
            "FRED API key",
            type="password",
            help="Leave blank to use FRED_API_KEY from the environment, .env, or Streamlit secrets.",
        )
        openai_api_key = ""
        if worker_mode == OPENAI_MODE:
            openai_api_key = st.text_input(
                "OpenAI API key",
                type="password",
                help="Leave blank to use OPENAI_API_KEY from the environment, .env, or Streamlit secrets.",
            )
        if env_fred_key:
            st.caption("FRED API key loaded from environment or secrets.")
        if worker_mode == OPENAI_MODE and env_openai_key:
            st.caption("OpenAI API key loaded from environment or secrets.")
        st.markdown("[Observability](./Observability)")

    st.header("Question")
    question = st.text_area(
        "Ask a FRED-answerable economics question",
        value=CANONICAL_QUESTION,
        height=96,
    )

    has_fred_api_key = bool(resolve_fred_api_key(fred_api_key))
    needs_openai_api_key = worker_mode == OPENAI_MODE
    has_openai_api_key = bool(resolve_openai_api_key(openai_api_key))
    if not has_fred_api_key:
        st.warning(
            "Set `FRED_API_KEY` in your environment, a `.env` file, Streamlit secrets, "
            "or the sidebar before running a live FRED analysis."
        )
    if needs_openai_api_key and not has_openai_api_key:
        st.warning("Set `OPENAI_API_KEY` to run the model-backed worker.")

    can_run = bool(
        question.strip()
        and has_fred_api_key
        and (not needs_openai_api_key or has_openai_api_key)
    )
    if st.button("Run through harness", disabled=not can_run, type="primary"):
        with st.status("Running harness", expanded=True) as status:
            st.write("Enforcing input guardrails and executing the FRED loop…")
            run_id = run_question(
                question,
                fred_api_key=fred_api_key,
                openai_api_key=openai_api_key,
                worker_mode=worker_mode,
            )
            st.session_state.current_run_id = run_id
            view = load_run_view(run_id)
            stage = (view.get("state") or {}).get("current_stage", "unknown")
            st.write(f"Run ID: `{run_id}`")
            st.write(f"Final stage: `{stage}`")
            if stage == "released":
                status.update(label="Released an answer", state="complete")
            elif stage == "escalated":
                status.update(label="Harness escalated this run", state="error")
            else:
                status.update(label="Harness finished with an incomplete run", state="error")

    run_id = st.session_state.get("current_run_id")
    if not run_id:
        st.info(
            "The canonical demo question is CPI over the last five years. Mock mode is "
            "deterministic; OpenAI mode can plan against other FRED-answerable questions."
        )
        return

    try:
        view = load_run_view(run_id)
    except FileNotFoundError:
        st.error(f"Run directory was not found for `{run_id}`.")
        return

    st.header("Harness Progress")
    _render_progress(view)
    _render_status(view)

    answer_column, chart_column = st.columns([3, 2])
    with answer_column:
        st.header("Answer")
        _render_answer(view)

    with chart_column:
        st.header("Chart")
        _render_chart(view)

    alarms = view.get("alarms") or view["artifacts"].get("alarms.json") or []
    if alarms:
        with st.expander("Alarms", expanded=_is_escalated(view)):
            st.json(alarms)

    with st.expander("Run artifacts"):
        st.write(f"Run ID: {run_id}")
        st.json(view.get("state") or {})


def _worker_pair(worker_mode: str, openai_api_key: str | None):
    if _is_openai_mode(worker_mode):
        key = resolve_openai_api_key(openai_api_key)
        return OpenAIWorker(api_key=key), OpenAIChecker(api_key=key)
    return MockWorker(), MockChecker()


def _is_openai_mode(worker_mode: str) -> bool:
    return worker_mode.strip().lower() in {"openai", OPENAI_MODE.lower()}


def _is_escalated(view: dict) -> bool:
    state = view.get("state") or {}
    return state.get("current_stage") == "escalated"


def _render_status(view: dict) -> None:
    state = view.get("state") or {}
    stage = state.get("current_stage", "unknown")
    retries = state.get("retry_count", 0)
    if stage == "released":
        st.success(f"Released after {retries} retr{'y' if retries == 1 else 'ies'}.")
        return
    if stage == "escalated":
        alarms = view.get("alarms") or view["artifacts"].get("alarms.json") or []
        latest = alarms[-1] if isinstance(alarms, list) and alarms else {}
        message = latest.get("message") if isinstance(latest, dict) else "The harness stopped this run."
        st.error(f"Escalated: {message}")
        return
    st.warning(f"Stopped at `{stage}` after {retries} retries.")


def _render_progress(view: dict) -> None:
    artifacts = view.get("artifacts", {})
    stages = [
        ("Input", "input.json"),
        ("Guardrails", "guardrails.json"),
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
        if _is_escalated(view):
            st.info("No answer was released. Inspect alarms and observability for the failure.")
        else:
            st.info("No released answer is available yet.")
        return

    st.write(final_answer.get("answer", "No answer released."))
    referenced_metrics = final_answer.get("referenced_metrics", [])
    if referenced_metrics:
        st.caption("Referenced metrics: " + ", ".join(referenced_metrics))
    selected = final_answer.get("selected_series") or []
    if selected:
        series_ids = [
            str(item.get("series_id"))
            for item in selected
            if isinstance(item, dict) and item.get("series_id")
        ]
        if series_ids:
            st.caption("FRED series: " + ", ".join(series_ids))


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
