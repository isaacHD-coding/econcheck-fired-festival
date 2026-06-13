"""Orchestrator skeleton for EconCheck run control."""

from __future__ import annotations

from datetime import date, datetime
import math
from pathlib import Path
from typing import Any

from harness.alarms import Alarm
from harness.persistence import save_artifact, save_run_state, save_text_artifact
from harness.state import RunState, Stage
from harness.tools.code_runner import run_analysis_code
from harness.tools.fred import fred_fetch, fred_search
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


class Orchestrator:
    """Owns stage progression, retries, escalation, and release decisions."""

    def __init__(
        self,
        state: RunState,
        runs_dir: str | Path = "runs",
        worker: Any | None = None,
        checker: Any | None = None,
        fred_api_key: str | None = None,
    ) -> None:
        self.state = state
        self.runs_dir = Path(runs_dir)
        self.worker = worker
        self.checker = checker
        self.fred_api_key = fred_api_key or None
        self._checks: list[dict[str, Any]] = []
        self._persist()

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

        try:
            plan = self._planning_stage()
            search_payload, selection, data = self._data_discovery_stage(plan)
            analysis = self._code_generation_stage(plan, data)
            draft = self._draft_answer_stage(plan, analysis)
            checker_artifact = self._checker_review_stage(
                plan,
                data,
                analysis,
                draft,
            )
            self._release_answer(draft, checker_artifact, search_payload, selection)
            return self.release()
        except Exception as exc:
            if self.state.current_stage is not Stage.ESCALATED:
                self._escalate_with_alarm(
                    type="stage_failed",
                    message=f"{self.state.current_stage.value} failed: {exc}",
                    context={"error": repr(exc)},
                    retry_from=self._retry_from_current_stage(),
                )
            raise

    def _planning_stage(self) -> PlannerArtifact:
        self._set_stage(Stage.PLANNING)
        plan = self.worker.plan(self.state.question, self.state)
        plan = PlannerArtifact.from_dict(plan.to_dict())
        self._save_json_artifact("plan", plan)
        return plan

    def _data_discovery_stage(
        self,
        plan: PlannerArtifact,
    ) -> tuple[dict[str, Any], DataSelectionArtifact, DataArtifact]:
        self._set_stage(Stage.DATA_DISCOVERY)

        queries = []
        flattened_results: list[dict[str, Any]] = []
        for query in plan.search_queries:
            results = fred_search(query, api_key=self.fred_api_key)
            result_dicts = [result.to_dict() for result in results]
            queries.append({"query": query, "results": result_dicts})
            flattened_results.extend(result_dicts)

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
            self._raise_with_alarm(
                type="data_selection_failed",
                message="Worker did not select any FRED series.",
                context={"selected_data": selection.to_dict()},
                retry_from="data_discovery",
            )

        data = fred_fetch(
            selected_ids,
            api_key=self.fred_api_key,
            observation_start=_five_years_ago(),
        )
        data.metadata["selected_series"] = selection.selected_series
        self._save_json_artifact("data", data)

        self._run_data_checks(selection, data, flattened_results)
        self._require_stage_checks_passed(Stage.DATA_DISCOVERY)
        return search_payload, selection, data

    def _code_generation_stage(
        self,
        plan: PlannerArtifact,
        data: DataArtifact,
    ) -> AnalysisArtifact:
        self._set_stage(Stage.CODE_GENERATION)

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
            self._raise_with_alarm(
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
        return analysis

    def _draft_answer_stage(
        self,
        plan: PlannerArtifact,
        analysis: AnalysisArtifact,
    ) -> DraftArtifact:
        self._set_stage(Stage.DRAFT_ANSWER)
        draft = self.worker.draft_answer(plan, analysis)
        draft = DraftArtifact.from_dict(draft.to_dict())
        self._save_json_artifact("draft", draft)

        self._run_answer_checks(plan, analysis, draft)
        self._require_stage_checks_passed(Stage.DRAFT_ANSWER)
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
            self._raise_with_alarm(
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
        searched_ids = {result.get("series_id") for result in search_results}
        self._record_check(
            "SourceProvenanceCheckpoint",
            Stage.DATA_DISCOVERY,
            all(series_id in searched_ids for series_id in selected_ids),
            "Selected series must come from live FRED search results.",
            {"selected_series": selected_ids},
        )

        counts = {
            series_id: len(data.observations.get(series_id, []))
            for series_id in selected_ids
        }
        self._record_check(
            "DataCompletenessCheckpoint",
            Stage.DATA_DISCOVERY,
            bool(counts) and all(count >= 48 for count in counts.values()),
            "Selected series must include at least 48 numeric observations.",
            {"observation_counts": counts},
        )

        latest_dates = {
            series_id: _latest_observation_date(data.observations.get(series_id, []))
            for series_id in selected_ids
        }
        freshness_passed = bool(latest_dates) and all(
            latest is not None and (date.today() - latest).days <= 150
            for latest in latest_dates.values()
        )
        self._record_check(
            "FreshnessCheckpoint",
            Stage.DATA_DISCOVERY,
            freshness_passed,
            "Latest CPI observations should reflect normal monthly release lag.",
            {
                "latest_dates": {
                    series_id: latest.isoformat() if latest is not None else None
                    for series_id, latest in latest_dates.items()
                }
            },
        )

        self._record_check(
            "InformationSufficiencyCheckpoint",
            Stage.DATA_DISCOVERY,
            "CPIAUCSL" in selected_ids and bool(data.observations.get("CPIAUCSL")),
            "CPIAUCSL observations are required for the canonical CPI question.",
            {"selected_series": selected_ids},
        )

    def _run_code_checks(self, analysis: AnalysisArtifact) -> None:
        self._record_check(
            "CodeExecutionCheckpoint",
            Stage.CODE_GENERATION,
            isinstance(analysis, AnalysisArtifact),
            "Generated code must execute and return an AnalysisArtifact.",
        )
        self._record_check(
            "OutputShapeCheckpoint",
            Stage.CODE_GENERATION,
            all(
                isinstance(value, list)
                for value in [
                    analysis.tables,
                    analysis.metrics,
                    analysis.claims,
                    analysis.charts,
                    analysis.warnings,
                ]
            )
            and isinstance(analysis.method_notes, str),
            "Analysis output must match the required outer schema.",
        )
        metric_values = [
            metric.get("value")
            for metric in analysis.metrics
            if isinstance(metric, dict) and isinstance(metric.get("value"), (int, float))
        ]
        self._record_check(
            "MathSanityCheckpoint",
            Stage.CODE_GENERATION,
            bool(metric_values)
            and all(math.isfinite(value) and abs(value) < 1000 for value in metric_values),
            "Metric values must be finite and plausibly scaled.",
            {"metric_values": metric_values},
        )
        self._record_check(
            "ChartPromiseCheckpoint",
            Stage.CODE_GENERATION,
            bool(analysis.charts),
            "Analysis must include chart descriptor data.",
        )

    def _run_answer_checks(
        self,
        plan: PlannerArtifact,
        analysis: AnalysisArtifact,
        draft: DraftArtifact,
    ) -> None:
        metric_names = {
            metric.get("name")
            for metric in analysis.metrics
            if isinstance(metric, dict) and isinstance(metric.get("name"), str)
        }
        referenced = set(draft.referenced_metrics)
        self._record_check(
            "AnswerGroundingCheckpoint",
            Stage.DRAFT_ANSWER,
            bool(referenced) and referenced.issubset(metric_names),
            "Draft answer must reference generated metric names.",
            {
                "referenced_metrics": sorted(referenced),
                "available_metrics": sorted(metric_names),
            },
        )
        self._record_check(
            "SuccessCriteriaCheckpoint",
            Stage.DRAFT_ANSWER,
            "CPI" in draft.answer and all(criteria for criteria in plan.success_criteria),
            "Draft answer must satisfy the plan success criteria.",
            {"success_criteria": plan.success_criteria},
        )

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
                "name": name,
                "stage": stage.value,
                "passed": bool(passed),
                "message": message,
                "context": context or {},
            }
        )
        self._save_json_artifact("checkpoint_results", {"checks": self._checks})

    def _require_stage_checks_passed(self, stage: Stage) -> None:
        failed = [
            check
            for check in self._checks
            if check["stage"] == stage.value and not check["passed"]
        ]
        if failed:
            self._raise_with_alarm(
                type="checkpoint_failed",
                message=f"{stage.value} checkpoint failed.",
                context={"checks": failed},
                retry_from=stage.value,
            )

    def _set_stage(self, stage: Stage) -> None:
        self.state.current_stage = stage
        self._persist()

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

    def _raise_with_alarm(
        self,
        *,
        type: str,
        message: str,
        context: dict[str, Any],
        retry_from: str,
    ) -> None:
        self._escalate_with_alarm(
            type=type,
            message=message,
            context=context,
            retry_from=retry_from,
        )
        raise RuntimeError(message)

    def _escalate_with_alarm(
        self,
        *,
        type: str,
        message: str,
        context: dict[str, Any],
        retry_from: str,
    ) -> None:
        alarm = Alarm(
            type=type,
            severity="error",
            stage=self.state.current_stage.value,
            message=message,
            context=context,
            recommended_action="retry",
            retry_from=retry_from,
        )
        self.escalate(alarm)
        self._persist_alarms()

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


def _five_years_ago() -> date:
    today = date.today()
    try:
        return today.replace(year=today.year - 5)
    except ValueError:
        return today.replace(month=2, day=28, year=today.year - 5)


def _latest_observation_date(rows: list[dict[str, Any]]) -> date | None:
    if not rows:
        return None
    try:
        return datetime.strptime(str(rows[-1]["date"]), "%Y-%m-%d").date()
    except (KeyError, TypeError, ValueError):
        return None
