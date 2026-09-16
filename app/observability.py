from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st


DEFAULT_RUNS_DIR = Path("runs")


def load_run_view(run_id: str, runs_dir: str | Path = DEFAULT_RUNS_DIR) -> dict[str, Any]:
    run_dir = Path(runs_dir) / run_id
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    artifacts: dict[str, Any] = {}
    artifact_paths: dict[str, str] = {}
    for path in sorted(run_dir.iterdir()):
        if not path.is_file():
            continue
        artifact_paths[path.name] = str(path)
        if path.suffix == ".json":
            artifacts[path.name] = json.loads(path.read_text(encoding="utf-8"))
        else:
            artifacts[path.name] = path.read_text(encoding="utf-8")

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "state": artifacts.get("state.json"),
        "alarms": artifacts.get("alarms.json", []),
        "artifacts": artifacts,
        "artifact_paths": artifact_paths,
    }


def list_run_ids(runs_dir: str | Path = DEFAULT_RUNS_DIR) -> list[str]:
    runs_path = Path(runs_dir)
    if not runs_path.is_dir():
        return []
    return sorted(
        path.name
        for path in runs_path.iterdir()
        if path.is_dir() and (path / "state.json").exists()
    )


CORE_ARTIFACTS = [
    "input.json",
    "guardrails.json",
    "plan.json",
    "fred_search.json",
    "selected_data.json",
    "data.json",
    "generated_code.py",
    "analysis.json",
    "checkpoint_results.json",
    "draft.json",
    "checker.json",
    "final_answer.json",
    "alarms.json",
    "timeline.json",
    "state.json",
]


def main() -> None:
    st.set_page_config(page_title="EconCheck Observability", layout="wide")
    st.title("Observability")
    st.caption("Read-only reconstruction of harness runs from persisted artifacts.")

    run_ids = list_run_ids()
    if not run_ids:
        st.info("No runs found yet. Submit a question from the Chat page first.")
        return

    default_index = len(run_ids) - 1
    current_run_id = st.session_state.get("current_run_id")
    if current_run_id in run_ids:
        default_index = run_ids.index(current_run_id)

    run_id = st.selectbox("Run", run_ids, index=default_index)
    view = load_run_view(run_id)
    artifacts = view.get("artifacts", {})
    state = view.get("state") or {}

    st.subheader("Run Summary")
    st.write(
        {
            "run_id": run_id,
            "question": state.get("question"),
            "current_stage": state.get("current_stage"),
            "retry_count": state.get("retry_count"),
            "max_turns": state.get("max_turns"),
        }
    )

    timeline = artifacts.get("timeline.json")
    if isinstance(timeline, list) and timeline:
        st.subheader("Timeline")
        st.table(
            [
                {
                    "stage": item.get("label") or item.get("stage_id"),
                    "status": item.get("status"),
                    "summary": item.get("summary"),
                }
                for item in timeline
                if isinstance(item, dict)
            ]
        )

    final_answer = artifacts.get("final_answer.json")
    if isinstance(final_answer, dict) and final_answer.get("answer"):
        st.subheader("Released Answer")
        st.write(final_answer["answer"])

    alarms = artifacts.get("alarms.json") or []
    if alarms:
        st.subheader("Alarms")
        st.json(alarms)

    st.subheader("Artifacts")
    for name in CORE_ARTIFACTS:
        if name not in artifacts:
            continue
        with st.expander(name, expanded=name in {"checkpoint_results.json", "guardrails.json"}):
            artifact = artifacts[name]
            if isinstance(artifact, str):
                st.code(artifact, language="python" if name.endswith(".py") else None)
            else:
                st.json(artifact)

    extra = sorted(set(artifacts) - set(CORE_ARTIFACTS))
    for name in extra:
        with st.expander(name):
            artifact = artifacts[name]
            if isinstance(artifact, str):
                st.code(artifact)
            else:
                st.json(artifact)


if __name__ == "__main__":
    main()
