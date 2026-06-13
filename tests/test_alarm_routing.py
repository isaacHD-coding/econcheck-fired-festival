import tempfile

from harness.checkpoints import (
    AnswerGroundingCheckpoint,
    CodeExecutionCheckpoint,
    OutputShapeCheckpoint,
    SourceProvenanceCheckpoint,
)
from harness.guardrails import (
    EconomicScopeGuardrail,
    PlannerSchemaGuardrail,
)
from harness.orchestrator import Orchestrator
from harness.state import RunState, Stage
from workers.artifacts import AnalysisArtifact, DraftArtifact


def state(stage: Stage) -> RunState:
    return RunState(
        run_id="routing-test",
        question="What happened to CPI inflation?",
        current_stage=stage,
        retry_count=0,
    )


def valid_analysis() -> AnalysisArtifact:
    return AnalysisArtifact(
        tables=[],
        metrics=[
            {
                "name": "latest_cpi",
                "value": 310.326,
                "unit": "index",
                "source_series": ["CPIAUCSL"],
            }
        ],
        claims=[],
        charts=[],
        method_notes="Computed from FRED data.",
        warnings=[],
    )


def test_input_guardrail_failure_alarm_routes_to_escalation():
    result = EconomicScopeGuardrail().evaluate("Who won the Super Bowl?")

    with tempfile.TemporaryDirectory() as tmpdir:
        routed = Orchestrator(state(Stage.INPUT), tmpdir).route_alarm(result.alarm)

    assert routed.current_stage is Stage.ESCALATED
    assert routed.alarms[0].recommended_action == "escalate"
    assert routed.alarms[0].stage == "input"


def test_planner_guardrail_failure_alarm_routes_retry_from_planning():
    result = PlannerSchemaGuardrail().evaluate({"question_type": "trend"})

    with tempfile.TemporaryDirectory() as tmpdir:
        routed = Orchestrator(state(Stage.PLANNING), tmpdir).route_alarm(result.alarm)

    assert routed.current_stage is Stage.PLANNING
    assert routed.retry_count == 1
    assert routed.alarms[0].recommended_action == "retry"
    assert routed.alarms[0].retry_from == "planning"


def test_source_provenance_alarm_routes_retry_from_code_generation():
    analysis = valid_analysis()
    analysis.metrics = [{"name": "latest_cpi"}]
    result = SourceProvenanceCheckpoint().evaluate(analysis)

    with tempfile.TemporaryDirectory() as tmpdir:
        routed = Orchestrator(state(Stage.DATA_DISCOVERY), tmpdir).route_alarm(
            result.alarm
        )

    assert routed.current_stage is Stage.CODE_GENERATION
    assert routed.retry_count == 1
    assert routed.alarms[0].retry_from == "code_generation"


def test_code_execution_alarm_routes_retry_from_code_generation():
    result = CodeExecutionCheckpoint().evaluate(
        {"succeeded": False, "execution_error": "NameError"}
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        routed = Orchestrator(state(Stage.CODE_GENERATION), tmpdir).route_alarm(
            result.alarm
        )

    assert routed.current_stage is Stage.CODE_GENERATION
    assert routed.retry_count == 1
    assert routed.alarms[0].retry_from == "code_generation"


def test_output_shape_alarm_routes_retry_from_code_generation():
    result = OutputShapeCheckpoint().evaluate({"tables": []})

    with tempfile.TemporaryDirectory() as tmpdir:
        routed = Orchestrator(state(Stage.CODE_GENERATION), tmpdir).route_alarm(
            result.alarm
        )

    assert routed.current_stage is Stage.CODE_GENERATION
    assert routed.retry_count == 1
    assert routed.alarms[0].retry_from == "code_generation"


def test_answer_grounding_alarm_routes_retry_from_draft_answer():
    result = AnswerGroundingCheckpoint().evaluate(
        DraftArtifact(answer="CPI rose.", referenced_metrics=["missing"], chart_paths=[]),
        valid_analysis(),
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        routed = Orchestrator(state(Stage.DRAFT_ANSWER), tmpdir).route_alarm(
            result.alarm
        )

    assert routed.current_stage is Stage.DRAFT_ANSWER
    assert routed.retry_count == 1
    assert routed.alarms[0].retry_from == "draft_answer"


def test_abort_alarm_routes_to_terminal_escalation_and_preserves_abort_action():
    result = OutputShapeCheckpoint().evaluate({"tables": []})
    result.alarm.recommended_action = "abort"

    with tempfile.TemporaryDirectory() as tmpdir:
        routed = Orchestrator(state(Stage.CODE_GENERATION), tmpdir).route_alarm(
            result.alarm
        )

    assert routed.current_stage is Stage.ESCALATED
    assert routed.alarms[0].recommended_action == "abort"
