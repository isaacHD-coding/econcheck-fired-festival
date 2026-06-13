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


def main() -> None:
    st.set_page_config(page_title="EconCheck Observability", layout="wide")
    st.title("Observability")

    run_ids = list_run_ids()
    if not run_ids:
        st.info("No runs found.")
        return

    run_id = st.selectbox("Run", run_ids, index=len(run_ids) - 1)
    view = load_run_view(run_id)
    state = view.get("state") or {}
    st.write(
        {
            "run_id": run_id,
            "current_stage": state.get("current_stage"),
            "retry_count": state.get("retry_count"),
        }
    )

    final_answer = view["artifacts"].get("final_answer.json")
    if isinstance(final_answer, dict) and final_answer.get("answer"):
        st.subheader("Released Answer")
        st.write(final_answer["answer"])

    for name, artifact in view["artifacts"].items():
        with st.expander(name):
            if isinstance(artifact, str):
                st.code(artifact)
            else:
                st.json(artifact)


if __name__ == "__main__":
    main()
