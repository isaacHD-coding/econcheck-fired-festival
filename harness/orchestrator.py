"""Orchestrator for EconCheck run control."""

from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any
from pathlib import Path

from harness.alarms import Alarm
from harness.checkpoints import (
    AnswerGroundingCheckpoint,
    ChartPromiseCheckpoint,
    CodeExecutionCheckpoint,
    DataCompletenessCheckpoint,
    FreshnessCheckpoint,
    InformationSufficiencyCheckpoint,
    MathSanityCheckpoint,
    OutputShapeCheckpoint,
    SourceProvenanceCheckpoint,
    SuccessCriteriaCheckpoint,
)
from harness.guardrails import INPUT_GUARDRAILS, PLANNING_GUARDRAILS
from harness.persistence import save_artifact, save_run_state, save_text_artifact
from harness.state import RunState, Stage
from harness.tools.code_runner import run_analysis_code
from harness.tools.fred import FredConfigurationError, FredToolError, fred_fetch, fred_search
from workers.artifacts import (
    AnalysisArtifact,
    CheckerArtifact,
    CodeArtifact,
    DataArtifact,
    DataSelectionArtifact,
    DraftArtifact,
    PlannerArtifact,
)


TERMINAL_STAGES = {Stage.RELEASED, Stage.ESCALATED}

NEXT_STAGE = {
    Stage.INPUT: Stage.PLANNING,
    Stage.PLANNING: Stage.DATA_DISCOVERY,
    Stage.DATA_DISCOVERY: Stage.CODE_GENERATION,
    Stage.CODE_GENERATION: Stage.DRAFT_ANSWER,
    Stage.DRAFT_ANSWER: Stage.CHECKER_REVIEW,
    Stage.CHECKER_REVIEW: Stage.RELEASED,
}

RETRY_STAGES = {
    "planning": Stage.PLANNING,
    "data_discovery": Stage.DATA_DISCOVERY,
    "code_generation": Stage.CODE_GENERATION,
    "draft_answer": Stage.DRAFT_ANSWER,
}

# Whole-run wall clock. OpenAI calls are separately capped at 45s with no SDK retries.
DEFAULT_RUN_DEADLINE_SECONDS = 240.0


class StageControl(Exception):
    """Interrupt the current stage after alarm routing."""

    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__(action)


class Orchestrator:
    """Owns stage progression, retries, escalation, and release decisions."""

    def __init__(
        self,
        state: RunState,
        runs_dir: str | Path = "runs",
        worker: Any | None = None,
        checker: Any | None = None,
        fred_api_key: str | None = None,
        progress_callback: Callable[[str, str], None] | None = None,
        deadline_seconds: float | None = DEFAULT_RUN_DEADLINE_SECONDS,
    ) -> None:
        self.state = state
        self.runs_dir = Path(runs_dir)
        self.worker = worker
        self.checker = checker
        self.fred_api_key = fred_api_key or None
        self.progress_callback = progress_callback
        self.deadline_seconds = deadline_seconds
        self._deadline_at = (
            None if deadline_seconds is None else time.monotonic() + deadline_seconds
        )
        self._loop_iterations = 0
        self._max_loop_iterations = max(8, (state.max_turns + 1) * 8)
        self._checks: list[dict[str, Any]] = []
        self._guardrails: list[dict[str, Any]] = []
        self._timeline: list[dict[str, Any]] = []
        self._persist()
        self._notify(state.current_stage.value, "Run started.")

    def run(self) -> RunState:
        if self.worker is not None:
            return self._run_integrated()

        while self.state.current_stage not in TERMINAL_STAGES:
            self.advance_stage()
        return self.state

    def advance_stage(self) -> RunState:
        if self.state.current_stage in TERMINAL_STAGES:
            return self.state

        next_stage = NEXT_STAGE.get(self.state.current_stage)
        if next_stage is None:
            return self.escalate()

        if next_stage is Stage.RELEASED:
            return self.release()

        self.state.current_stage = next_stage
        self._persist()
        return self.state

    def retry(self, alarm: Alarm | None = None, retry_from: str | Stage | None = None) -> RunState:
        if alarm is not None:
            self.state.alarms.append(alarm)

        self.state.retry_count += 1
        if self.state.retry_count > self.state.max_turns:
            return self.escalate(alarm)

        target = retry_from
        if target is None and alarm is not None:
            target = alarm.retry_from

        self.state.current_stage = self._normalize_retry_stage(target)
        self._persist()
        return self.state

    def route_alarm(self, alarm: Alarm) -> RunState:
        if alarm.recommended_action == "retry":
            return self.retry(alarm)
        if alarm.recommended_action == "escalate":
            return self.escalate(alarm)
        if alarm.recommended_action == "abort":
            return self.abort(alarm)

        raise ValueError(f"Unknown alarm action: {alarm.recommended_action!r}")

    def release(self) -> RunState:
        self.state.current_stage = Stage.RELEASED
        self._persist()
        return self.state

    def escalate(self, alarm: Alarm | None = None) -> RunState:
        if alarm is not None and alarm not in self.state.alarms:
            self.state.alarms.append(alarm)
        self.state.current_stage = Stage.ESCALATED
        self._persist()
        return self.state

    def abort(self, alarm: Alarm | None = None) -> RunState:
        if alarm is not None and alarm not in self.state.alarms:
            self.state.alarms.append(alarm)
        self.state.current_stage = Stage.ESCALATED
        self._persist()
        return self.state

    def _persist(self) -> None:
        save_run_state(self.state, self.runs_dir)

    def _normalize_retry_stage(self, retry_from: str | Stage | None) -> Stage:
        if retry_from is None:
            return self.state.current_stage
        if isinstance(retry_from, Stage):
            return retry_from

        try:
            return RETRY_STAGES[retry_from]
        except KeyError as exc:
            raise ValueError(f"Unknown retry target: {retry_from!r}") from exc

    def _run_integrated(self) -> RunState:
        if self.checker is None:
            raise ValueError("Integrated runs require a checker.")

        self._save_json_artifact(
            "input",
            {"run_id": self.state.run_id, "question": self.state.question},
        )
        self._persist_alarms()

        context: dict[str, Any] = {}
        try:
            self._run_input_guardrails()
            self._require_fred_configured()
            if self.state.current_stage is Stage.INPUT:
                self._set_stage(Stage.PLANNING)
        except StageControl:
            return self.state

        while self.state.current_stage not in TERMINAL_STAGES:
            self._loop_iterations += 1
            try:
                self._raise_if_over_budget()
                self._continue_from_current_stage(context)
            except StageControl as control:
                if control.action != "retry" or self.state.current_stage in TERMINAL_STAGES:
                    return self.state
            except Exception as exc:
                if self.state.current_stage is not Stage.ESCALATED:
                    try:
                        self._fail_with_alarm(
                            type="stage_failed",
                            message=f"{self.state.current_stage.value} failed: {exc}",
                            context={"error": repr(exc)},
                            retry_from=self._retry_from_current_stage(),
                            recommended_action="escalate",
                        )
                    except StageControl:
                        return self.state
                return self.state
        return self.state

    def _continue_from_current_stage(self, context: dict[str, Any]) -> None:
        stage = self.state.current_stage
        if stage is Stage.PLANNING:
            context["plan"] = self._planning_stage()
            self._set_stage(Stage.DATA_DISCOVERY)
            return
        if stage is Stage.DATA_DISCOVERY:
            plan = context.get("plan") or self._planning_stage()
            context["plan"] = plan
            search_payload, selection, data = self._data_discovery_stage(plan)
            context["search_payload"] = search_payload
            context["selection"] = selection
            context["data"] = data
            self._set_stage(Stage.CODE_GENERATION)
            return
        if stage is Stage.CODE_GENERATION:
            plan = context.get("plan") or self._planning_stage()
            data = context.get("data")
            if data is None:
                search_payload, selection, data = self._data_discovery_stage(plan)
                context["search_payload"] = search_payload
                context["selection"] = selection
                context["data"] = data
            context["plan"] = plan
            context["analysis"] = self._code_generation_stage(plan, data)
            self._set_stage(Stage.DRAFT_ANSWER)
            return
        if stage is Stage.DRAFT_ANSWER:
            plan = context.get("plan") or self._planning_stage()
            analysis = context.get("analysis")
            if analysis is None:
                data = context.get("data")
                if data is None:
                    _, _, data = self._data_discovery_stage(plan)
                    context["data"] = data
                analysis = self._code_generation_stage(plan, data)
                context["analysis"] = analysis
            context["plan"] = plan
            context["draft"] = self._draft_answer_stage(plan, analysis)
            self._set_stage(Stage.CHECKER_REVIEW)
            return
        if stage is Stage.CHECKER_REVIEW:
            plan = context.get("plan") or self._planning_stage()
            data = context.get("data")
            analysis = context.get("analysis")
            draft = context.get("draft")
            if data is None or analysis is None or draft is None:
                raise RuntimeError("Checker review is missing required artifacts.")
            checker_artifact = self._checker_review_stage(plan, data, analysis, draft)
            self._release_answer(
                draft,
                checker_artifact,
                context.get("search_payload") or {},
                context.get("selection") or DataSelectionArtifact([], [], ""),
            )
            self._append_timeline(
                "release",
                "Release",
                "complete",
                "draft",
                "Grounded answer released.",
            )
            self.release()
            return

        self.escalate()

    def _run_input_guardrails(self) -> None:
        self._set_stage(Stage.INPUT)
        for guardrail in INPUT_GUARDRAILS:
            result = guardrail.evaluate(self.state.question)
            self._record_guardrail(guardrail.__class__.__name__, "input", result)
            if not result.passed:
                self._fail_from_result(result.alarm, default_action="escalate")
        self._append_timeline(
            "input_guardrails",
            "Input Guardrails",
            "complete",
            "guardrails",
            "Question passed economic-scope and safety checks.",
        )

    def _require_fred_configured(self) -> None:
        from harness.config import resolve_fred_api_key

        if resolve_fred_api_key(self.fred_api_key):
            return
        self._fail_with_alarm(
            type="fred_not_configured",
            message=(
                "FRED_API_KEY is not configured. Set it in your environment, a "
                ".env file, or Streamlit secrets."
            ),
            context={},
            retry_from="data_discovery",
            recommended_action="escalate",
        )

    def _planning_stage(self) -> PlannerArtifact:
        self._set_stage(Stage.PLANNING)
        self._append_timeline(
            "planning",
            "Planning",
            "in_progress",
            "planner",
            "Requesting a plan from the worker.",
        )
        plan = self.worker.plan(self.state.question, self.state)
        plan = PlannerArtifact.from_dict(plan.to_dict())
        self._save_json_artifact("plan", plan)
        for guardrail in PLANNING_GUARDRAILS:
            result = guardrail.evaluate(plan)
            self._record_guardrail(guardrail.__class__.__name__, "planning", result)
            if not result.passed:
                self._fail_from_result(result.alarm, default_action="retry")
        self._append_timeline(
            "planning",
            "Planning",
            "complete",
            "planner",
            "Planner produced a structured FRED analysis plan.",
        )
        return plan

    def _data_discovery_stage(
        self,
        plan: PlannerArtifact,
    ) -> tuple[dict[str, Any], DataSelectionArtifact, DataArtifact]:
        self._set_stage(Stage.DATA_DISCOVERY)
        self._append_timeline(
            "data_discovery",
            "Data Discovery",
            "in_progress",
            "data_selection",
            "Searching FRED and selecting series.",
        )

        queries = []
        flattened_results: list[dict[str, Any]] = []
        try:
            for query in plan.search_queries:
                results = fred_search(query, api_key=self.fred_api_key)
                result_dicts = [result.to_dict() for result in results]
                queries.append({"query": query, "results": result_dicts})
                flattened_results.extend(result_dicts)
        except FredConfigurationError as exc:
            self._fail_with_alarm(
                type="fred_not_configured",
                message=str(exc),
                context={"error": repr(exc)},
                retry_from="data_discovery",
                recommended_action="escalate",
            )
        except FredToolError as exc:
            self._fail_with_alarm(
                type="fred_search_failed",
                message=str(exc),
                context={"error": repr(exc)},
                retry_from="data_discovery",
            )

        search_payload = {"queries": queries}
        self._save_json_artifact("fred_search", search_payload)

        selection = self.worker.select_data(plan, flattened_results)
        selection = DataSelectionArtifact.from_dict(selection.to_dict())
        self._save_json_artifact("selected_data", selection)

        selected_ids = [
            str(series.get("series_id"))
            for series in selection.selected_series
            if series.get("series_id")
        ]
        if not selected_ids:
            self._fail_with_alarm(
                type="data_selection_failed",
                message="Worker did not select any FRED series.",
                context={"selected_data": selection.to_dict()},
                retry_from="data_discovery",
            )

        try:
            data = fred_fetch(
                selected_ids,
                api_key=self.fred_api_key,
                observation_start=_five_years_ago(),
            )
        except FredConfigurationError as exc:
            self._fail_with_alarm(
                type="fred_not_configured",
                message=str(exc),
                context={"error": repr(exc)},
                retry_from="data_discovery",
                recommended_action="escalate",
            )
        except FredToolError as exc:
            self._fail_with_alarm(
                type="fred_fetch_failed",
                message=str(exc),
                context={"error": repr(exc), "selected_series": selected_ids},
                retry_from="data_discovery",
            )

        data.metadata["selected_series"] = selection.selected_series
        self._save_json_artifact("data", data)

        self._run_data_checks(selection, data, flattened_results)
        self._require_stage_checks_passed(Stage.DATA_DISCOVERY)
        self._append_timeline(
            "data_discovery",
            "Data Discovery",
            "complete",
            "data_selection",
            "Harness searched FRED and fetched selected observations.",
        )
        return search_payload, selection, data

    def _code_generation_stage(
        self,
        plan: PlannerArtifact,
        data: DataArtifact,
    ) -> AnalysisArtifact:
        self._set_stage(Stage.CODE_GENERATION)
        self._append_timeline(
            "code_generation",
            "Code Generation",
            "in_progress",
            "code",
            "Writing and executing analysis code.",
        )

        code_artifact = self.worker.write_code(plan, data)
        code_artifact = CodeArtifact.from_dict(code_artifact.to_dict())
        self._save_text_artifact("generated_code", "generated_code.py", code_artifact.code)

        code_output_path = self._run_dir() / "code_output.json"
        self.state.artifacts["code_output"] = "code_output.json"
        self._persist()

        try:
            analysis = run_analysis_code(
                code_artifact,
                data,
                output_log_path=code_output_path,
            )
        except Exception as exc:
            self._apply_checkpoint(CodeExecutionCheckpoint().evaluate({
                "succeeded": False,
                "execution_error": repr(exc),
            }))
            self._fail_with_alarm(
                type="code_execution_failed",
                message="Generated analysis code failed.",
                context={
                    "generated_code_path": str(self._run_dir() / "generated_code.py"),
                    "code_output_path": str(code_output_path),
                    "error": repr(exc),
                },
                retry_from="code_generation",
            )

        analysis = AnalysisArtifact.from_dict(analysis.to_dict())
        self._save_json_artifact("analysis", analysis)

        self._run_code_checks(analysis)
        self._require_stage_checks_passed(Stage.CODE_GENERATION)
        self._append_timeline(
            "code_generation",
            "Code Generation",
            "complete",
            "code",
            "Harness executed worker-generated analysis code.",
        )
        return analysis

    def _draft_answer_stage(
        self,
        plan: PlannerArtifact,
        analysis: AnalysisArtifact,
    ) -> DraftArtifact:
        self._set_stage(Stage.DRAFT_ANSWER)
        self._append_timeline(
            "draft_answer",
            "Draft Answer",
            "in_progress",
            "analysis",
            "Drafting the user-facing answer.",
        )
        draft = self.worker.draft_answer(plan, analysis)
        draft = DraftArtifact.from_dict(draft.to_dict())
        self._save_json_artifact("draft", draft)

        self._run_answer_checks(plan, analysis, draft)
        self._require_stage_checks_passed(Stage.DRAFT_ANSWER)
        self._append_timeline(
            "draft_answer",
            "Draft Answer",
            "complete",
            "analysis",
            "Worker drafted a grounded user-facing answer.",
        )
        return draft

    def _checker_review_stage(
        self,
        plan: PlannerArtifact,
        data: DataArtifact,
        analysis: AnalysisArtifact,
        draft: DraftArtifact,
    ) -> CheckerArtifact:
        self._set_stage(Stage.CHECKER_REVIEW)
        checker_artifact = self.checker.review(self.state, plan, data, analysis, draft)
        checker_artifact = CheckerArtifact.from_dict(checker_artifact.to_dict())
        self._save_json_artifact("checker", checker_artifact)

        if not checker_artifact.passed:
            self._fail_with_alarm(
                type="checker_failed",
                message="Checker did not approve the draft answer.",
                context=checker_artifact.to_dict(),
                retry_from=checker_artifact.retry_from or "draft_answer",
            )
        return checker_artifact

    def _release_answer(
        self,
        draft: DraftArtifact,
        checker_artifact: CheckerArtifact,
        search_payload: dict[str, Any],
        selection: DataSelectionArtifact,
    ) -> None:
        self._save_json_artifact(
            "final_answer",
            {
                "run_id": self.state.run_id,
                "answer": draft.answer,
                "referenced_metrics": draft.referenced_metrics,
                "chart_paths": draft.chart_paths,
                "checker": checker_artifact.to_dict(),
                "fred_search_queries": [
                    item["query"] for item in search_payload.get("queries", [])
                ],
                "selected_series": selection.selected_series,
                "released": True,
            },
        )
        self._persist_alarms()

    def _run_data_checks(
        self,
        selection: DataSelectionArtifact,
        data: DataArtifact,
        search_results: list[dict[str, Any]],
    ) -> None:
        selected_ids = [series["series_id"] for series in selection.selected_series]
        self._apply_checkpoint(
            SourceProvenanceCheckpoint().evaluate(selection, search_results),
            name="SourceProvenanceCheckpoint",
            stage=Stage.DATA_DISCOVERY,
        )
        self._apply_checkpoint(
            DataCompletenessCheckpoint().evaluate(
                data,
                selected_series=selection.selected_series,
            ),
            name="DataCompletenessCheckpoint",
            stage=Stage.DATA_DISCOVERY,
        )
        self._apply_checkpoint(
            FreshnessCheckpoint().evaluate(data, selected_ids=selected_ids),
            name="FreshnessCheckpoint",
            stage=Stage.DATA_DISCOVERY,
        )
        self._apply_checkpoint(
            InformationSufficiencyCheckpoint().evaluate(
                data,
                selected_ids=selected_ids,
                question=self.state.question,
            ),
            name="InformationSufficiencyCheckpoint",
            stage=Stage.DATA_DISCOVERY,
        )

    def _run_code_checks(self, analysis: AnalysisArtifact) -> None:
        self._apply_checkpoint(
            CodeExecutionCheckpoint().evaluate(analysis),
            name="CodeExecutionCheckpoint",
            stage=Stage.CODE_GENERATION,
        )
        self._apply_checkpoint(
            OutputShapeCheckpoint().evaluate(analysis),
            name="OutputShapeCheckpoint",
            stage=Stage.CODE_GENERATION,
        )
        self._apply_checkpoint(
            SourceProvenanceCheckpoint().evaluate(analysis),
            name="MetricSourceProvenanceCheckpoint",
            stage=Stage.CODE_GENERATION,
        )
        self._apply_checkpoint(
            MathSanityCheckpoint().evaluate(analysis),
            name="MathSanityCheckpoint",
            stage=Stage.CODE_GENERATION,
        )
        self._apply_checkpoint(
            ChartPromiseCheckpoint().evaluate(analysis),
            name="ChartPromiseCheckpoint",
            stage=Stage.CODE_GENERATION,
        )

    def _run_answer_checks(
        self,
        plan: PlannerArtifact,
        analysis: AnalysisArtifact,
        draft: DraftArtifact,
    ) -> None:
        self._apply_checkpoint(
            AnswerGroundingCheckpoint().evaluate(draft, analysis),
            name="AnswerGroundingCheckpoint",
            stage=Stage.DRAFT_ANSWER,
        )
        self._apply_checkpoint(
            SuccessCriteriaCheckpoint().evaluate(
                draft,
                analysis,
                plan=plan,
                question=self.state.question,
            ),
            name="SuccessCriteriaCheckpoint",
            stage=Stage.DRAFT_ANSWER,
        )

    def _apply_checkpoint(
        self,
        result: Any,
        *,
        name: str,
        stage: Stage,
    ) -> None:
        passed = bool(getattr(result, "passed", False))
        message = getattr(result, "reason", "") or (
            result.alarm.message if getattr(result, "alarm", None) is not None else ""
        )
        context = {}
        if getattr(result, "alarm", None) is not None:
            context = dict(result.alarm.context or {})
        self._record_check(name, stage, passed, message, context)

    def _record_check(
        self,
        name: str,
        stage: Stage,
        passed: bool,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        self._checks.append(
            {
                "kind": "checkpoint",
                "name": name,
                "stage": stage.value,
                "passed": bool(passed),
                "status": "passed" if passed else "failed",
                "message": message,
                "context": context or {},
            }
        )
        self._save_json_artifact("checkpoint_results", {"checks": self._checks})

    def _record_guardrail(self, name: str, stage: str, result: Any) -> None:
        self._guardrails.append(
            {
                "kind": "guardrail",
                "name": name,
                "stage": stage,
                "status": "passed" if result.passed else "failed",
                "message": result.reason,
            }
        )
        self._save_json_artifact("guardrails", self._guardrails)

    def _append_timeline(
        self,
        stage_id: str,
        label: str,
        status: str,
        artifact_key: str,
        summary: str,
    ) -> None:
        self._timeline = [item for item in self._timeline if item.get("stage_id") != stage_id]
        self._timeline.append(
            {
                "stage_id": stage_id,
                "label": label,
                "status": status,
                "artifact_key": artifact_key,
                "summary": summary,
            }
        )
        self._save_json_artifact("timeline", self._timeline)

    def _require_stage_checks_passed(self, stage: Stage) -> None:
        failed = [
            check
            for check in self._checks
            if check["stage"] == stage.value and not check["passed"]
        ]
        if failed:
            self._fail_with_alarm(
                type="checkpoint_failed",
                message=f"{stage.value} checkpoint failed.",
                context={"checks": failed},
                retry_from=stage.value,
            )

    def _set_stage(self, stage: Stage) -> None:
        self.state.current_stage = stage
        self._checks = [check for check in self._checks if check["stage"] != stage.value]
        if self._checks:
            self._save_json_artifact("checkpoint_results", {"checks": self._checks})
        self._persist()
        self._notify(stage.value, f"Entered {stage.value}.")
        self._raise_if_over_budget()

    def _notify(self, stage: str, message: str) -> None:
        if self.progress_callback is None:
            return
        try:
            self.progress_callback(stage, message)
        except Exception:
            return

    def _raise_if_over_budget(self) -> None:
        if self._loop_iterations > self._max_loop_iterations:
            self._fail_with_alarm(
                type="run_iteration_limit",
                message=(
                    f"Run exceeded the stage-loop cap ({self._max_loop_iterations} "
                    "iterations) and was stopped instead of spinning forever."
                ),
                context={
                    "loop_iterations": self._loop_iterations,
                    "max_loop_iterations": self._max_loop_iterations,
                    "retry_count": self.state.retry_count,
                    "max_turns": self.state.max_turns,
                },
                retry_from=self._retry_from_current_stage(),
                recommended_action="escalate",
            )
        if self._deadline_at is not None and time.monotonic() >= self._deadline_at:
            limit = self.deadline_seconds if self.deadline_seconds is not None else 0
            self._fail_with_alarm(
                type="run_deadline_exceeded",
                message=(
                    f"Run exceeded the {limit:.0f}s wall-clock limit and was "
                    "stopped instead of hanging."
                ),
                context={
                    "deadline_seconds": self.deadline_seconds,
                    "current_stage": self.state.current_stage.value,
                    "retry_count": self.state.retry_count,
                },
                retry_from=self._retry_from_current_stage(),
                recommended_action="escalate",
            )

    def _save_json_artifact(self, name: str, artifact: Any) -> Path:
        path = save_artifact(self.state.run_id, name, artifact, self.runs_dir)
        self.state.artifacts[name] = path.name
        self._persist()
        return path

    def _save_text_artifact(self, key: str, filename: str, text: str) -> Path:
        path = save_text_artifact(self.state.run_id, filename, text, self.runs_dir)
        self.state.artifacts[key] = path.name
        self._persist()
        return path

    def _persist_alarms(self) -> None:
        self._save_json_artifact(
            "alarms",
            [alarm.to_dict() for alarm in self.state.alarms],
        )

    def _fail_from_result(self, alarm: Alarm | None, *, default_action: str) -> None:
        if alarm is None:
            alarm = Alarm(
                type="guardrail_failed",
                severity="error",
                stage=self.state.current_stage.value,
                message="Guardrail failed.",
                context={},
                recommended_action=default_action,
                retry_from=self._retry_from_current_stage(),
            )
        self.route_alarm(alarm)
        self._persist_alarms()
        if self.state.current_stage in TERMINAL_STAGES:
            raise StageControl("halt")
        raise StageControl("retry")

    def _fail_with_alarm(
        self,
        *,
        type: str,
        message: str,
        context: dict[str, Any],
        retry_from: str,
        recommended_action: str = "retry",
    ) -> None:
        alarm = Alarm(
            type=type,
            severity="error",
            stage=self.state.current_stage.value,
            message=message,
            context=context,
            recommended_action=recommended_action,
            retry_from=retry_from,
        )
        self.route_alarm(alarm)
        self._persist_alarms()
        if self.state.current_stage in TERMINAL_STAGES:
            raise StageControl("halt")
        raise StageControl("retry")

    def _retry_from_current_stage(self) -> str:
        if self.state.current_stage in {
            Stage.PLANNING,
            Stage.DATA_DISCOVERY,
            Stage.CODE_GENERATION,
            Stage.DRAFT_ANSWER,
        }:
            return self.state.current_stage.value
        return "draft_answer"

    def _run_dir(self) -> Path:
        return self.runs_dir / self.state.run_id


def _five_years_ago():
    from datetime import date

    today = date.today()
    try:
        return today.replace(year=today.year - 5)
    except ValueError:
        return today.replace(month=2, day=28, year=today.year - 5)
