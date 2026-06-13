from __future__ import annotations

import json
from pathlib import Path

import app.chat as chat
from harness.state import Stage
from workers.openai_client import resolve_openai_api_key


QUESTION = "What has happened to CPI inflation over the last five years?"


def test_run_question_passes_openai_key_to_openai_worker_and_checker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIWorker:
        def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
            captured["worker_api_key"] = api_key
            captured["worker_model"] = model

    class FakeOpenAIChecker:
        def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
            captured["checker_api_key"] = api_key
            captured["checker_model"] = model

    class FakeOrchestrator:
        def __init__(self, state, runs_dir, worker, checker, fred_api_key=None) -> None:
            captured["fred_api_key"] = fred_api_key
            self.state = state
            self.runs_dir = Path(runs_dir)

        def run(self):
            self.state.current_stage = Stage.RELEASED
            run_dir = self.runs_dir / self.state.run_id
            run_dir.mkdir(parents=True)
            (run_dir / "state.json").write_text(
                json.dumps(self.state.to_dict()),
                encoding="utf-8",
            )
            (run_dir / "final_answer.json").write_text(
                json.dumps({"answer": "released"}),
                encoding="utf-8",
            )
            return self.state

    monkeypatch.setattr(chat, "OpenAIWorker", FakeOpenAIWorker)
    monkeypatch.setattr(chat, "OpenAIChecker", FakeOpenAIChecker)
    monkeypatch.setattr(chat, "Orchestrator", FakeOrchestrator)

    run_id = chat.run_question(
        QUESTION,
        runs_dir=tmp_path,
        fred_api_key="fred-key",
        openai_api_key="judge-key",
        worker_mode="openai",
    )

    assert run_id.startswith("run-")
    assert captured["worker_api_key"] == "judge-key"
    assert captured["checker_api_key"] == "judge-key"
    assert captured["fred_api_key"] == "fred-key"
    assert "judge-key" not in _all_artifact_text(tmp_path / run_id)


def test_resolve_openai_api_key_falls_back_to_environment(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    assert resolve_openai_api_key(None) == "env-key"


def _all_artifact_text(run_dir: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in run_dir.iterdir()
        if path.is_file()
    )
