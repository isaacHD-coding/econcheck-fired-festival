from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import harness.orchestrator as orchestrator_module
from harness.checkpoints.base import CheckpointResult
from harness.state import RunState, Stage
from harness.tools.fred import SeriesSearchResult
from workers.artifacts import DataArtifact
from workers.mock_checker import MockChecker
from workers.mock_worker import MockWorker
from harness.orchestrator import (
    DEFAULT_RUN_DEADLINE_SECONDS,
    MAX_OPENAI_TIMEOUT_RETRIES_PER_STAGE,
    MIN_TIMEOUT_RETRY_SECONDS,
    Orchestrator,
)
from workers.openai_client import (
    DEFAULT_OPENAI_MAX_RETRIES,
    DEFAULT_OPENAI_TIMEOUT_SECONDS,
    OPENAI_DESIGN_CHART_TIMEOUT_SECONDS,
    OPENAI_DRAFT_TIMEOUT_SECONDS,
    OPENAI_PLAN_TIMEOUT_SECONDS,
    OPENAI_SELECT_DATA_TIMEOUT_SECONDS,
    OPENAI_WRITE_CODE_TIMEOUT_SECONDS,
    OpenAITimeoutError,
    call_openai_json,
    openai_timeout_seconds,
    user_facing_openai_timeout_message,
)
from workers.openai_worker import OpenAIWorkerTimeoutError


ISAAC_QUESTION = (
    "What is the correlation (or anti correlation) between inflation and real GDP growth?"
)


def test_stuck_planning_stage_hits_iteration_cap_instead_of_spinning(tmp_path, monkeypatch) -> None:
    calls = {"n": 0}

    def stuck(self, context) -> None:
        calls["n"] += 1
        if calls["n"] > 200:
            raise AssertionError("unbounded retry")

    monkeypatch.setattr(Orchestrator, "_continue_from_current_stage", stuck)
    monkeypatch.setattr(
        orchestrator_module,
        "fred_search",
        lambda *args, **kwargs: [_cpi_search_result()],
    )

    state = RunState(
        run_id="stuck-plan",
        question=ISAAC_QUESTION,
        current_stage=Stage.INPUT,
        retry_count=0,
        max_turns=2,
    )
    final_state = Orchestrator(
        state,
        runs_dir=tmp_path,
        worker=MockWorker(),
        checker=MockChecker(),
        fred_api_key="judge-key",
        deadline_seconds=None,
    ).run()

    assert final_state.current_stage is Stage.ESCALATED
    assert calls["n"] <= 24
    assert any(alarm.type == "run_iteration_limit" for alarm in final_state.alarms)


def test_openai_multiseries_retry_loop_stops_at_max_turns(tmp_path, monkeypatch) -> None:
    plan_calls = {"n": 0}

    class CountingWorker(MockWorker):
        def plan(self, question, state):
            plan_calls["n"] += 1
            if plan_calls["n"] > 50:
                raise AssertionError("unbounded planning retries")
            return super().plan(question, state)

    def fail_data(*args, **kwargs):
        return CheckpointResult.fail_result(
            checkpoint_name="InformationSufficiencyCheckpoint",
            stage="data_discovery",
            message="forced relationship-data failure",
            retry_from="data_discovery",
        )

    monkeypatch.setattr(
        orchestrator_module.InformationSufficiencyCheckpoint,
        "evaluate",
        fail_data,
    )
    monkeypatch.setattr(orchestrator_module, "fred_search", _search_cpi_and_gdp)
    monkeypatch.setattr(orchestrator_module, "fred_fetch", _fetch_cpi_and_gdp)

    state = RunState(
        run_id="retry-cap",
        question=ISAAC_QUESTION,
        current_stage=Stage.INPUT,
        retry_count=0,
        max_turns=2,
    )
    final_state = Orchestrator(
        state,
        runs_dir=tmp_path,
        worker=CountingWorker(),
        checker=MockChecker(),
        fred_api_key="judge-key",
        deadline_seconds=None,
    ).run()

    assert final_state.current_stage is Stage.ESCALATED
    assert final_state.retry_count > final_state.max_turns
    assert plan_calls["n"] < 20
    assert any(
        alarm.retry_from == "data_discovery" or alarm.type == "checkpoint_failed"
        for alarm in final_state.alarms
    )


def test_fast_failures_hit_deadline_instead_of_running_forever(tmp_path, monkeypatch) -> None:
    def fail_data(*args, **kwargs):
        time.sleep(0.02)
        return CheckpointResult.fail_result(
            checkpoint_name="InformationSufficiencyCheckpoint",
            stage="data_discovery",
            message="forced failure",
            retry_from="data_discovery",
        )

    monkeypatch.setattr(
        orchestrator_module.InformationSufficiencyCheckpoint,
        "evaluate",
        fail_data,
    )
    monkeypatch.setattr(orchestrator_module, "fred_search", _search_cpi_and_gdp)
    monkeypatch.setattr(orchestrator_module, "fred_fetch", _fetch_cpi_and_gdp)

    state = RunState(
        run_id="deadline",
        question=ISAAC_QUESTION,
        current_stage=Stage.INPUT,
        retry_count=0,
        max_turns=100,
    )
    final_state = Orchestrator(
        state,
        runs_dir=tmp_path,
        worker=MockWorker(),
        checker=MockChecker(),
        fred_api_key="judge-key",
        deadline_seconds=0.2,
    ).run()

    assert final_state.current_stage is Stage.ESCALATED
    assert final_state.retry_count < 100
    assert any(alarm.type == "run_deadline_exceeded" for alarm in final_state.alarms)


def test_progress_callback_reports_planning_before_worker_returns(tmp_path, monkeypatch) -> None:
    events: list[tuple[str, str]] = []

    class BlockingThenOk(MockWorker):
        def plan(self, question, state):
            assert any(stage == "planning" for stage, _message in events)
            return super().plan(question, state)

    monkeypatch.setattr(orchestrator_module, "fred_search", _search_cpi_and_gdp)
    monkeypatch.setattr(orchestrator_module, "fred_fetch", _fetch_cpi_and_gdp)

    state = RunState(
        run_id="progress",
        question=ISAAC_QUESTION,
        current_stage=Stage.INPUT,
        retry_count=0,
    )
    Orchestrator(
        state,
        runs_dir=tmp_path,
        worker=BlockingThenOk(),
        checker=MockChecker(),
        fred_api_key="judge-key",
        progress_callback=lambda stage, message: events.append((stage, message)),
    ).run()

    assert events
    assert any(stage == "planning" for stage, _message in events)


def test_call_openai_json_disables_sdk_retries_and_sets_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponses:
        def create(self, **kwargs):
            return SimpleNamespace(output_text='{"ok": true}', output=[])

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    parsed = call_openai_json(
        schema_name="probe",
        schema={"type": "object"},
        instructions="return json",
        input_payload={"q": "hi"},
        api_key="test-key",
    )

    assert parsed == {"ok": True}
    timeout = captured["timeout"]
    read_timeout = getattr(timeout, "read", timeout)
    assert float(read_timeout) == DEFAULT_OPENAI_TIMEOUT_SECONDS
    assert captured["max_retries"] == DEFAULT_OPENAI_MAX_RETRIES


def test_call_openai_json_hard_timeout_returns_before_blocking_create_finishes(
    monkeypatch,
) -> None:
    started = time.monotonic()

    class FakeResponses:
        def create(self, **kwargs):
            time.sleep(5)

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    with pytest.raises(OpenAITimeoutError, match="timed out"):
        call_openai_json(
            schema_name="probe",
            schema={"type": "object"},
            instructions="return json",
            input_payload={"q": "hi"},
            api_key="test-key",
            timeout_seconds=0.3,
        )

    assert time.monotonic() - started < 1.5


def test_stage_timeout_config_gives_codegen_a_longer_budget() -> None:
    assert OPENAI_WRITE_CODE_TIMEOUT_SECONDS == 120.0
    assert OPENAI_DESIGN_CHART_TIMEOUT_SECONDS == 60.0
    assert OPENAI_PLAN_TIMEOUT_SECONDS == 30.0
    assert OPENAI_SELECT_DATA_TIMEOUT_SECONDS == 30.0
    assert OPENAI_DRAFT_TIMEOUT_SECONDS == 30.0
    assert openai_timeout_seconds(stage_label="write_code") == 120.0
    assert openai_timeout_seconds(schema_name="code_artifact") == 120.0
    assert openai_timeout_seconds(stage_label="design_chart") == 60.0
    assert openai_timeout_seconds(stage_label="plan") == 30.0
    assert openai_timeout_seconds(stage_label="select_data") == 30.0
    assert openai_timeout_seconds(stage_label="draft_answer") == 30.0
    assert openai_timeout_seconds(schema_name="checker_artifact") == 30.0
    assert openai_timeout_seconds(stage_label="write_code", cap_seconds=40.0) == 40.0
    assert openai_timeout_seconds(stage_label="plan", cap_seconds=40.0) == 30.0
    assert DEFAULT_RUN_DEADLINE_SECONDS == 180.0
    assert MAX_OPENAI_TIMEOUT_RETRIES_PER_STAGE == 1
    assert MIN_TIMEOUT_RETRY_SECONDS == 15.0
    assert OPENAI_WRITE_CODE_TIMEOUT_SECONDS < DEFAULT_RUN_DEADLINE_SECONDS
    message = user_facing_openai_timeout_message("write_code", 120.0)
    assert "Code generation" in message
    assert "120" in message
    assert "OpenAIWorkerError" not in message


def test_call_openai_json_uses_code_artifact_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponses:
        def create(self, **kwargs):
            return SimpleNamespace(output_text='{"code": "analysis_output = {}"}', output=[])

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    call_openai_json(
        schema_name="code_artifact",
        schema={"type": "object"},
        instructions="return json",
        input_payload={"q": "hi"},
        api_key="test-key",
    )

    timeout = captured["timeout"]
    read_timeout = getattr(timeout, "read", timeout)
    assert float(read_timeout) == OPENAI_WRITE_CODE_TIMEOUT_SECONDS


def test_code_generation_timeout_retries_once_then_succeeds(tmp_path, monkeypatch) -> None:
    class TimeoutOnce(MockWorker):
        def __init__(self) -> None:
            self.write_calls = 0

        def write_code(self, plan, data, chart_brief=None):
            self.write_calls += 1
            if self.write_calls == 1:
                raise OpenAIWorkerTimeoutError(
                    "write_code",
                    OPENAI_WRITE_CODE_TIMEOUT_SECONDS,
                    schema_name="code_artifact",
                )
            return super().write_code(plan, data, chart_brief=chart_brief)

    monkeypatch.setattr(orchestrator_module, "fred_search", _search_cpi_and_gdp)
    monkeypatch.setattr(orchestrator_module, "fred_fetch", _fetch_cpi_and_gdp)

    worker = TimeoutOnce()
    final_state = Orchestrator(
        RunState(
            run_id="timeout-retry",
            question=ISAAC_QUESTION,
            current_stage=Stage.INPUT,
            retry_count=0,
        ),
        runs_dir=tmp_path,
        worker=worker,
        checker=MockChecker(),
        fred_api_key="judge-key",
        deadline_seconds=None,
    ).run()

    assert final_state.current_stage is Stage.RELEASED
    assert worker.write_calls == 2
    timeout_alarms = [alarm for alarm in final_state.alarms if alarm.type == "stage_timeout"]
    assert len(timeout_alarms) == 1
    assert timeout_alarms[0].recommended_action == "retry"
    assert timeout_alarms[0].retry_from == "code_generation"
    assert "OpenAIWorkerError" not in timeout_alarms[0].message
    assert "did not match" not in timeout_alarms[0].message
    assert "Code generation" in timeout_alarms[0].message


def test_code_generation_timeout_escalates_after_one_retry(tmp_path, monkeypatch) -> None:
    class AlwaysTimeout(MockWorker):
        def __init__(self) -> None:
            self.write_calls = 0

        def write_code(self, plan, data, chart_brief=None):
            self.write_calls += 1
            raise OpenAIWorkerTimeoutError(
                "write_code",
                OPENAI_WRITE_CODE_TIMEOUT_SECONDS,
                schema_name="code_artifact",
            )

    monkeypatch.setattr(orchestrator_module, "fred_search", _search_cpi_and_gdp)
    monkeypatch.setattr(orchestrator_module, "fred_fetch", _fetch_cpi_and_gdp)

    worker = AlwaysTimeout()
    final_state = Orchestrator(
        RunState(
            run_id="timeout-escalate",
            question=ISAAC_QUESTION,
            current_stage=Stage.INPUT,
            retry_count=0,
        ),
        runs_dir=tmp_path,
        worker=worker,
        checker=MockChecker(),
        fred_api_key="judge-key",
        deadline_seconds=None,
    ).run()

    assert final_state.current_stage is Stage.ESCALATED
    assert worker.write_calls == 2
    timeout_alarms = [alarm for alarm in final_state.alarms if alarm.type == "stage_timeout"]
    assert len(timeout_alarms) == 2
    assert timeout_alarms[0].recommended_action == "retry"
    assert timeout_alarms[1].recommended_action == "escalate"
    assert all("OpenAIWorkerError" not in alarm.message for alarm in timeout_alarms)
    assert all("Code generation" in alarm.message for alarm in timeout_alarms)


def test_timeout_retry_requires_remaining_run_budget(tmp_path) -> None:
    state = RunState(
        run_id="timeout-budget",
        question=ISAAC_QUESTION,
        current_stage=Stage.CODE_GENERATION,
        retry_count=0,
    )
    orchestrator = Orchestrator(
        state,
        runs_dir=tmp_path,
        deadline_seconds=DEFAULT_RUN_DEADLINE_SECONDS,
    )
    orchestrator._deadline_at = time.monotonic() + 5.0
    assert orchestrator._should_retry_openai_timeout("code_generation") is False

    unlimited = Orchestrator(
        RunState(
            run_id="timeout-unlimited",
            question=ISAAC_QUESTION,
            current_stage=Stage.CODE_GENERATION,
            retry_count=0,
        ),
        runs_dir=tmp_path,
        deadline_seconds=None,
    )
    assert unlimited._should_retry_openai_timeout("code_generation") is True
    unlimited._timeout_retries["code_generation"] = 1
    assert unlimited._should_retry_openai_timeout("code_generation") is False


def test_ctrl_c_persists_escalation_instead_of_swallowing_interrupt(tmp_path) -> None:
    class BlockingWorker(MockWorker):
        def plan(self, question, state):
            raise KeyboardInterrupt()

    state = RunState(
        run_id="interrupt",
        question=ISAAC_QUESTION,
        current_stage=Stage.INPUT,
        retry_count=0,
    )
    orchestrator = Orchestrator(
        state,
        runs_dir=tmp_path,
        worker=BlockingWorker(),
        checker=MockChecker(),
        fred_api_key="judge-key",
        deadline_seconds=None,
    )

    with pytest.raises(KeyboardInterrupt):
        orchestrator.run()

    assert orchestrator.state.current_stage is Stage.ESCALATED
    assert any(alarm.type == "run_interrupted" for alarm in orchestrator.state.alarms)


def _cpi_search_result() -> SeriesSearchResult:
    return SeriesSearchResult(
        series_id="CPIAUCSL",
        title="CPI",
        frequency="Monthly",
        units="Index",
        observation_start="1947-01-01",
        observation_end="2026-08-01",
    )


def _gdp_search_result() -> SeriesSearchResult:
    return SeriesSearchResult(
        series_id="GDPC1",
        title="Real GDP",
        frequency="Quarterly",
        units="Billions",
        observation_start="1947-01-01",
        observation_end="2026-04-01",
    )


def _search_cpi_and_gdp(query: str, *, api_key: str | None = None):
    query_l = query.lower()
    if "gdp" in query_l:
        return [_gdp_search_result()]
    return [_cpi_search_result()]


def _fetch_cpi_and_gdp(series_ids, *, api_key=None, observation_start=None):
    from datetime import date

    observations = {}
    today = date.today()
    for series_id in series_ids:
        rows = []
        for index in range(21 if series_id == "GDPC1" else 61):
            month_index = today.month - 1 + index * (3 if series_id == "GDPC1" else 1)
            year = today.year - 5 + month_index // 12
            month = month_index % 12 + 1
            rows.append(
                {
                    "series_id": series_id,
                    "date": f"{year:04d}-{month:02d}-01",
                    "value": 100.0 + index,
                }
            )
        observations[series_id] = rows
    return DataArtifact(
        series_ids=list(series_ids),
        observations=observations,
        metadata={"source": "FRED", "series": {}},
    )
