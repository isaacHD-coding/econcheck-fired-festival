from __future__ import annotations

import json
from pathlib import Path

import app.chat as chat
import harness.orchestrator as orchestrator_module
from harness.orchestrator import Orchestrator
from harness.state import RunState, Stage
from harness.tools.fred import SeriesSearchResult
from workers.artifacts import DataArtifact
from workers.mock_checker import MockChecker
from workers.mock_worker import MockWorker


QUESTION = "What has happened to CPI inflation over the last five years?"


def test_orchestrator_passes_explicit_fred_api_key_to_fred_tools(
    monkeypatch,
    tmp_path: Path,
) -> None:
    seen: dict[str, list[str | None]] = {"search": [], "fetch": []}

    def fake_fred_search(query: str, *, api_key: str | None = None):
        seen["search"].append(api_key)
        return [
            SeriesSearchResult(
                series_id="CPIAUCSL",
                title=(
                    "Consumer Price Index for All Urban Consumers: "
                    "All Items in U.S. City Average"
                ),
                frequency="Monthly",
                units="Index 1982-1984=100",
                observation_start="1947-01-01",
                observation_end="2026-05-01",
            )
        ]

    def fake_fred_fetch(
        series_ids: list[str],
        *,
        api_key: str | None = None,
        observation_start=None,
    ) -> DataArtifact:
        seen["fetch"].append(api_key)
        return DataArtifact(
            series_ids=series_ids,
            observations={"CPIAUCSL": _fresh_cpi_rows()},
            metadata={"source": "FRED", "series": {}},
        )

    monkeypatch.setattr(orchestrator_module, "fred_search", fake_fred_search)
    monkeypatch.setattr(orchestrator_module, "fred_fetch", fake_fred_fetch)

    state = RunState(
        run_id="api-key-flow",
        question=QUESTION,
        current_stage=Stage.INPUT,
        retry_count=0,
    )
    final_state = Orchestrator(
        state,
        runs_dir=tmp_path,
        worker=MockWorker(),
        checker=MockChecker(),
        fred_api_key="judge-key",
    ).run()

    assert final_state.current_stage is Stage.RELEASED
    assert seen == {"search": ["judge-key"], "fetch": ["judge-key"]}
    assert "judge-key" not in _all_artifact_text(tmp_path / "api-key-flow")


def test_run_question_passes_explicit_fred_api_key_to_orchestrator(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeOrchestrator:
        def __init__(
            self,
            state,
            runs_dir,
            worker,
            checker,
            fred_api_key: str | None = None,
        ) -> None:
            captured["state"] = state
            captured["runs_dir"] = runs_dir
            captured["fred_api_key"] = fred_api_key

        def run(self):
            return captured["state"]

    monkeypatch.setattr(chat, "Orchestrator", FakeOrchestrator)

    run_id = chat.run_question(
        QUESTION,
        runs_dir=tmp_path,
        fred_api_key="judge-key",
    )

    assert run_id.startswith("run-")
    assert captured["runs_dir"] == tmp_path
    assert captured["fred_api_key"] == "judge-key"


def _fresh_cpi_rows() -> list[dict[str, object]]:
    rows = []
    for index in range(61):
        month_index = 5 + index
        year = 2021 + month_index // 12
        month = month_index % 12 + 1
        rows.append(
            {
                "series_id": "CPIAUCSL",
                "date": f"{year:04d}-{month:02d}-01",
                "value": 260.0 + index,
            }
        )
    return rows


def _all_artifact_text(run_dir: Path) -> str:
    parts = []
    for path in run_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix == ".json":
            parts.append(json.dumps(json.loads(path.read_text(encoding="utf-8"))))
        else:
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)
