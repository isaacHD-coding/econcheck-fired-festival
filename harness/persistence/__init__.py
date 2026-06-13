"""Simple JSON persistence for EconCheck run artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from harness.state import RunState


DEFAULT_RUNS_DIR = Path("runs")
STATE_FILENAME = "state.json"


def save_run_state(state: RunState, runs_dir: str | Path = DEFAULT_RUNS_DIR) -> Path:
    run_dir = _run_dir(state.run_id, runs_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    path = run_dir / STATE_FILENAME
    _write_json(path, state.to_dict())
    return path


def load_run_state(run_id: str, runs_dir: str | Path = DEFAULT_RUNS_DIR) -> RunState:
    path = _run_dir(run_id, runs_dir) / STATE_FILENAME
    return RunState.from_dict(_read_json(path))


def save_artifact(
    run_id: str,
    artifact_name: str,
    artifact: Any,
    runs_dir: str | Path = DEFAULT_RUNS_DIR,
) -> Path:
    run_dir = _run_dir(run_id, runs_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    path = run_dir / _json_filename(artifact_name)
    _write_json(path, _json_ready(artifact))
    return path


def save_text_artifact(
    run_id: str,
    artifact_name: str,
    text: str,
    runs_dir: str | Path = DEFAULT_RUNS_DIR,
) -> Path:
    run_dir = _run_dir(run_id, runs_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    path = run_dir / artifact_name
    path.write_text(text, encoding="utf-8")
    return path


def load_artifact(
    run_id: str,
    artifact_name: str,
    runs_dir: str | Path = DEFAULT_RUNS_DIR,
) -> Any:
    path = _run_dir(run_id, runs_dir) / _json_filename(artifact_name)
    return _read_json(path)


def _run_dir(run_id: str, runs_dir: str | Path) -> Path:
    return Path(runs_dir) / run_id


def _json_filename(artifact_name: str) -> str:
    path = Path(artifact_name)
    if path.suffix == ".json":
        return artifact_name
    return f"{artifact_name}.json"


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _json_ready(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    return value
