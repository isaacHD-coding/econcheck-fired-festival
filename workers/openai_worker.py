"""OpenAI-backed EconCheck worker implementation."""

from __future__ import annotations

import json
from typing import Any, TypeVar

from harness.domain import (
    is_canonical_cpi_demo_question,
    is_relationship_question,
    plan_requests_relationship,
)
from harness.state import RunState
from workers.analysis_templates import (
    canonical_cpi_analysis_code,
    canonical_cpi_draft,
    looks_like_canned_cpi_draft,
    relationship_analysis_code,
    relationship_draft,
)
from workers.artifacts import (
    AnalysisArtifact,
    ArtifactValidationError,
    ChartBriefArtifact,
    CodeArtifact,
    DataArtifact,
    DataSelectionArtifact,
    DraftArtifact,
    PlannerArtifact,
)
from workers.chart_briefs import CHART_DESIGN_ADVICE, build_chart_brief, repair_chart_brief
from workers.openai_client import DEFAULT_OPENAI_MODEL, OpenAIClientError, call_openai_json


class OpenAIWorkerError(RuntimeError):
    """Raised when a model artifact cannot be accepted by the harness."""


ArtifactT = TypeVar(
    "ArtifactT",
    PlannerArtifact,
    DataSelectionArtifact,
    ChartBriefArtifact,
    CodeArtifact,
    DraftArtifact,
)


class OpenAIWorker:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model or DEFAULT_OPENAI_MODEL
        self.question = ""

    def plan(self, question: str, state: RunState) -> PlannerArtifact:
        self.question = question
        payload = {
            "question": question,
            "state": state.to_dict(),
        }
        extra = (
            "If the question asks about a relationship, correlation, anti-correlation, "
            "or more than one concept (for example inflation and real GDP), plan "
            "separate FRED search queries for each concept. Do not collapse that "
            "question into a CPI-only five-year trend. The canonical CPI demo "
            "question may prefer a query that can find CPIAUCSL. Charting is a later "
            "worker step: the plan should name the claim a chart must support, not "
            "dump every fetched series onto one axis."
        )
        return self._call_artifact(
            schema_name="planner_artifact",
            schema=PLANNER_SCHEMA,
            instructions=_stage_instructions(
                "Planning",
                "Create a concise economic analysis plan for the user's question.",
                extra,
            ),
            input_payload=payload,
            artifact_cls=PlannerArtifact,
            stage_label="plan",
        )

    def select_data(
        self,
        plan: PlannerArtifact,
        search_results: list,
    ) -> DataSelectionArtifact:
        payload = {
            "plan": plan.to_dict(),
            "search_results": _json_ready(search_results),
        }
        selection = self._call_artifact(
            schema_name="data_selection_artifact",
            schema=DATA_SELECTION_SCHEMA,
            instructions=_stage_instructions(
                "Data selection",
                "Select the FRED series that best satisfies the plan using only the provided search results.",
                (
                    "Select every series the plan needs when those series appear in "
                    "search_results. Relationship questions that mention inflation and "
                    "real GDP should select CPIAUCSL and GDPC1 when both are present. "
                    "Do not invent series that are absent from the search results. "
                    "For the canonical CPI-only demo, CPIAUCSL is enough."
                ),
            ),
            input_payload=payload,
            artifact_cls=DataSelectionArtifact,
            stage_label="select_data",
        )
        if _needs_relationship_analysis(self.question, plan, None) and selection.selected_series:
            selection = _ensure_search_backed_series(
                selection,
                search_results,
                _wanted_relationship_series(self.question, plan, search_results),
            )
        if not selection.selected_series:
            if _needs_relationship_analysis(self.question, plan, None):
                recovered = _relationship_selection(search_results, self.question, plan)
                if recovered is not None:
                    return recovered
            if _allow_canonical_cpi_selection_recovery(self.question, plan):
                canonical_selection = _canonical_cpi_selection(search_results)
                if canonical_selection is not None:
                    return canonical_selection
        return selection

    def design_chart(
        self,
        plan: PlannerArtifact,
        data_summary: DataArtifact,
    ) -> ChartBriefArtifact:
        fallback = build_chart_brief(plan, data_summary, question=self.question)
        payload = {
            "plan": plan.to_dict(),
            "data": data_summary.to_dict(),
            "fallback_brief": fallback.to_dict(),
        }
        try:
            brief = self._call_artifact(
                schema_name="chart_brief_artifact",
                schema=CHART_BRIEF_SCHEMA,
                instructions=_stage_instructions(
                    "Chart design",
                    "Produce a structured chart brief that analysis codegen must follow.",
                    (
                        CHART_DESIGN_ADVICE
                        + " Use only series_ids present in the supplied DataArtifact. "
                        "Do not invent FRED ids. Canonical CPI-only demos may keep a "
                        "simple single line chart. For inflation vs real GDP correlation, "
                        "prefer period-over-period growth on a shared percent axis, with "
                        "dual-axis or stacked levels only as a companion when native "
                        "units would dwarf a series."
                    ),
                ),
                input_payload=payload,
                artifact_cls=ChartBriefArtifact,
                stage_label="design_chart",
            )
        except OpenAIWorkerError:
            return fallback
        return repair_chart_brief(brief, plan, data_summary, question=self.question)

    def write_code(
        self,
        plan: PlannerArtifact,
        data_summary: DataArtifact,
        chart_brief: ChartBriefArtifact | None = None,
    ) -> CodeArtifact:
        brief = chart_brief or build_chart_brief(plan, data_summary, question=self.question)
        if hasattr(data_summary, "metadata") and isinstance(data_summary.metadata, dict):
            data_summary.metadata["chart_brief"] = brief.to_dict()
        payload = {
            "plan": plan.to_dict(),
            "data": data_summary.to_dict(),
            "chart_brief": brief.to_dict(),
        }
        code_artifact = self._call_artifact(
            schema_name="code_artifact",
            schema=CODE_SCHEMA,
            instructions=_stage_instructions(
                "Code generation",
                "Write complete Python analysis code for the supplied DataArtifact.",
                (
                    "Return Python only in the JSON code field. The code must assign "
                    "analysis_output as a dict. Top-level analysis_output['tables'], "
                    "analysis_output['metrics'], analysis_output['claims'], "
                    "analysis_output['charts'], and analysis_output['warnings'] must "
                    "all be lists. analysis_output['method_notes'] must be a string. "
                    "Use only input_data. Do not call FRED, do not use the network, "
                    "do not use subprocesses, do not install packages, and do not "
                    "read or write files. Use only the Python standard library. "
                    "If input_data contains more than one series, analyze the "
                    "relationship among those series (aligned growth-rate correlation "
                    "is acceptable) instead of a CPI-only five-year trend. "
                    + CHART_DESIGN_ADVICE
                    + " Follow chart_brief exactly: claim, series_ids, transforms, "
                    "layout (single|dual_axis|stacked), y_starts_at_zero, title, "
                    "axis labels/units, notes, and chart_type. Every multi-series "
                    "chart must label units and cite FRED series ids. Never overlay "
                    "raw series with incompatible scales on one shared y-axis."
                ),
            ),
            input_payload=payload,
            artifact_cls=CodeArtifact,
            stage_label="write_code",
        )
        series_ids = _series_ids(data_summary)
        if _allow_canonical_cpi_fallback(self.question, plan, data_summary):
            return CodeArtifact(code=canonical_cpi_analysis_code())
        if _needs_relationship_analysis(self.question, plan, data_summary) and not _code_references_all_series(
            code_artifact.code,
            series_ids,
        ):
            return CodeArtifact(code=relationship_analysis_code())
        return code_artifact

    def draft_answer(
        self,
        plan: PlannerArtifact,
        analysis: AnalysisArtifact,
    ) -> DraftArtifact:
        payload = {
            "plan": plan.to_dict(),
            "analysis": analysis.to_dict(),
        }
        draft = self._call_artifact(
            schema_name="draft_artifact",
            schema=DRAFT_SCHEMA,
            instructions=_stage_instructions(
                "Draft answer",
                "Draft the user-facing answer using only the provided AnalysisArtifact.",
                (
                    "Do not invent numbers. Cite generated metric names in "
                    "referenced_metrics. Include chart references from analysis.charts "
                    "as analysis.json#charts/{index} when charts are available. "
                    "Answer the user's actual question. If the analysis includes a "
                    "relationship or correlation metric, explain that relationship; "
                    "do not replace it with a CPI-only five-year paragraph."
                ),
            ),
            input_payload=payload,
            artifact_cls=DraftArtifact,
            stage_label="draft_answer",
        )
        if _allow_canonical_cpi_fallback(self.question, plan, analysis) and _is_canonical_cpi_analysis(analysis):
            return canonical_cpi_draft(analysis)
        if _is_relationship_analysis(analysis) and (
            looks_like_canned_cpi_draft(draft) or not _draft_mentions_relationship(draft)
        ):
            return relationship_draft(analysis)
        return draft

    def _call_artifact(
        self,
        *,
        schema_name: str,
        schema: dict[str, Any],
        instructions: str,
        input_payload: dict[str, Any],
        artifact_cls: type[ArtifactT],
        stage_label: str,
    ) -> ArtifactT:
        try:
            data = call_openai_json(
                schema_name=schema_name,
                schema=schema,
                instructions=instructions,
                input_payload=input_payload,
                api_key=self.api_key,
                model=self.model,
            )
            return artifact_cls.from_dict(data)
        except (ArtifactValidationError, OpenAIClientError, TypeError, ValueError) as exc:
            raise OpenAIWorkerError(
                f"OpenAI {stage_label} response did not match {artifact_cls.__name__}: {exc}"
            ) from exc


def _stage_instructions(stage: str, objective: str, extra: str) -> str:
    return "\n".join(
        [
            f"Current stage: {stage}.",
            f"Objective: {objective}",
            HARNESS_BOUNDARY_RULES,
            extra,
            "Return only JSON matching the provided strict JSON schema.",
        ]
    )


def _json_ready(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    try:
        json.dumps(value)
    except TypeError:
        return repr(value)
    return value


def _canonical_cpi_selection(search_results: list) -> DataSelectionArtifact | None:
    normalized = _normalize_search_results(search_results)
    selected = _find_series(normalized, "CPIAUCSL")
    if selected is None:
        return None

    selected["reason"] = (
        selected.get("reason")
        or "CPIAUCSL is the canonical all-items CPI series for urban consumers."
    )
    rejected = [
        {**item, "reason": item.get("reason") or "Not the canonical CPIAUCSL series."}
        for item in normalized
        if item.get("series_id") != "CPIAUCSL"
    ]
    return DataSelectionArtifact(
        selected_series=[selected],
        rejected_series=rejected,
        justification=(
            "Recovered canonical CPI selection after the model returned no selected "
            "series. CPIAUCSL was present in the harness-provided FRED search results."
        ),
    )


def _relationship_selection(
    search_results: list,
    question: str,
    plan: PlannerArtifact,
) -> DataSelectionArtifact | None:
    wanted = _wanted_relationship_series(question, plan, search_results)
    selected = []
    normalized = _normalize_search_results(search_results)
    for series_id in wanted:
        item = _find_series(normalized, series_id)
        if item is None:
            continue
        item = dict(item)
        item["reason"] = item.get("reason") or (
            f"{series_id} is required for the planned relationship analysis."
        )
        selected.append(item)
    if len(selected) < 2:
        return None
    selected_ids = {item.get("series_id") for item in selected}
    rejected = [
        {**item, "reason": item.get("reason") or "Not required for the relationship analysis."}
        for item in normalized
        if item.get("series_id") not in selected_ids
    ]
    return DataSelectionArtifact(
        selected_series=selected,
        rejected_series=rejected,
        justification=(
            "Selected relationship series from harness-provided FRED search results "
            "without inventing identifiers."
        ),
    )


def _ensure_search_backed_series(
    selection: DataSelectionArtifact,
    search_results: list,
    wanted_ids: list[str],
) -> DataSelectionArtifact:
    normalized = _normalize_search_results(search_results)
    searched_ids = {item.get("series_id") for item in normalized}
    selected = [dict(item) for item in selection.selected_series]
    selected_ids = {item.get("series_id") for item in selected}
    for series_id in wanted_ids:
        if series_id in selected_ids or series_id not in searched_ids:
            continue
        item = _find_series(normalized, series_id)
        if item is None:
            continue
        item = dict(item)
        item["reason"] = item.get("reason") or (
            f"{series_id} is present in FRED search results and needed by the plan."
        )
        selected.append(item)
        selected_ids.add(series_id)
    if [item.get("series_id") for item in selected] == [
        item.get("series_id") for item in selection.selected_series
    ]:
        return selection
    rejected = [
        {**item, "reason": item.get("reason") or "Not selected for this plan."}
        for item in normalized
        if item.get("series_id") not in selected_ids
    ]
    return DataSelectionArtifact(
        selected_series=selected,
        rejected_series=rejected,
        justification=(
            selection.justification
            + " Additional planned series were added only because they appeared in "
            "the harness-provided FRED search results."
        ),
    )


def _wanted_relationship_series(question: str, plan: PlannerArtifact, search_results: list) -> list[str]:
    text = f"{question} {_plan_blob(plan)}".lower()
    normalized = _normalize_search_results(search_results)
    searched_ids = [str(item.get("series_id")) for item in normalized if item.get("series_id")]
    wanted: list[str] = []
    if "CPIAUCSL" in searched_ids and (
        "inflation" in text or "cpi" in text or "cpiaucsl" in text
    ):
        wanted.append("CPIAUCSL")
    if "GDPC1" in searched_ids and ("gdp" in text or "gdpc1" in text or "gross domestic" in text):
        wanted.append("GDPC1")
    for series_id in searched_ids:
        if series_id not in wanted and series_id.lower() in text:
            wanted.append(series_id)
    return wanted


def _allow_canonical_cpi_selection_recovery(question: str, plan: Any) -> bool:
    if is_relationship_question(question) or plan_requests_relationship(plan):
        return False
    return not question or is_canonical_cpi_demo_question(question)


def _allow_canonical_cpi_fallback(question: str, plan: Any, data_or_search: Any) -> bool:
    if is_relationship_question(question) or plan_requests_relationship(plan):
        return False
    series_ids = _series_ids(data_or_search)
    if len(series_ids) > 1:
        return False
    if question and not is_canonical_cpi_demo_question(question):
        return False
    if series_ids and set(series_ids) != {"CPIAUCSL"}:
        return False
    return True


def _needs_relationship_analysis(question: str, plan: Any, data: Any) -> bool:
    if is_relationship_question(question) or plan_requests_relationship(plan):
        return True
    series_ids = _series_ids(data)
    return len(series_ids) > 1


def _is_canonical_cpi_analysis(analysis: AnalysisArtifact) -> bool:
    metric_names = {
        metric.get("name")
        for metric in analysis.metrics
        if isinstance(metric, dict) and isinstance(metric.get("name"), str)
    }
    return {
        "cpi_five_year_change_percent",
        "latest_yoy_inflation_percent",
        "latest_cpi_index",
    }.issubset(metric_names) and "growth_correlation" not in metric_names


def _is_relationship_analysis(analysis: AnalysisArtifact) -> bool:
    metric_names = {
        metric.get("name")
        for metric in analysis.metrics
        if isinstance(metric, dict) and isinstance(metric.get("name"), str)
    }
    if "growth_correlation" in metric_names:
        return True
    source_series = {
        str(series_id)
        for metric in analysis.metrics
        if isinstance(metric, dict)
        for series_id in (metric.get("source_series") or [])
    }
    return len(source_series) > 1


def _draft_mentions_relationship(draft: DraftArtifact) -> bool:
    text = draft.answer.lower()
    return any(
        term in text
        for term in ("correlation", "anti-correlation", "anticorrelation", "relationship")
    )


def _code_references_all_series(code: str, series_ids: list[str]) -> bool:
    if len(series_ids) < 2:
        return True
    return all(series_id in code for series_id in series_ids)


def _series_ids(data_or_search: Any) -> list[str]:
    if data_or_search is None:
        return []
    if hasattr(data_or_search, "series_ids") and data_or_search.series_ids:
        return [str(item) for item in data_or_search.series_ids]
    if hasattr(data_or_search, "observations") and data_or_search.observations:
        return [str(item) for item in data_or_search.observations]
    if isinstance(data_or_search, dict):
        if data_or_search.get("series_ids"):
            return [str(item) for item in data_or_search["series_ids"]]
        if data_or_search.get("observations"):
            return [str(item) for item in data_or_search["observations"]]
    if isinstance(data_or_search, list):
        ids: list[str] = []
        for item in _normalize_search_results(data_or_search):
            series_id = item.get("series_id")
            if isinstance(series_id, str) and series_id not in ids:
                ids.append(series_id)
        return ids
    return []


def _normalize_search_results(search_results: list) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in search_results:
        if hasattr(item, "to_dict"):
            normalized.append(item.to_dict())
        elif isinstance(item, dict):
            normalized.append(dict(item))
    return normalized


def _find_series(search_results: list[dict[str, Any]], series_id: str) -> dict[str, Any] | None:
    for item in search_results:
        if item.get("series_id") == series_id:
            return dict(item)
    return None


def _plan_blob(plan: PlannerArtifact) -> str:
    data = plan.to_dict()
    parts = [data.get("measurement_strategy", "")]
    for key in (
        "economic_concepts",
        "search_queries",
        "information_requirements",
        "required_outputs",
        "success_criteria",
    ):
        parts.extend(str(item) for item in data.get(key, []))
    return " ".join(parts)


HARNESS_BOUNDARY_RULES = (
    "Harness boundary rules: you are the worker only. You may plan, select data, "
    "design charts, write code, and draft answers. You may not call FRED, fetch data, "
    "execute code, route retries, escalate failures, or release answers. The harness "
    "owns tools, execution, checkpoints, alarms, persistence, observability, and release."
)


STRING_ARRAY = {"type": "array", "items": {"type": "string"}}

PLANNER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "question_type": {"type": "string"},
        "economic_concepts": STRING_ARRAY,
        "measurement_strategy": {"type": "string"},
        "information_requirements": STRING_ARRAY,
        "search_queries": STRING_ARRAY,
        "required_outputs": STRING_ARRAY,
        "success_criteria": STRING_ARRAY,
    },
    "required": [
        "question_type",
        "economic_concepts",
        "measurement_strategy",
        "information_requirements",
        "search_queries",
        "required_outputs",
        "success_criteria",
    ],
}

SERIES_SELECTION_ITEM: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "series_id": {"type": "string"},
        "title": {"type": "string"},
        "frequency": {"type": "string"},
        "units": {"type": "string"},
        "observation_start": {"type": "string"},
        "observation_end": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": [
        "series_id",
        "title",
        "frequency",
        "units",
        "observation_start",
        "observation_end",
        "reason",
    ],
}

DATA_SELECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "selected_series": {"type": "array", "items": SERIES_SELECTION_ITEM},
        "rejected_series": {"type": "array", "items": SERIES_SELECTION_ITEM},
        "justification": {"type": "string"},
    },
    "required": ["selected_series", "rejected_series", "justification"],
}

CODE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "code": {"type": "string"},
    },
    "required": ["code"],
}

CHART_BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "claim": {"type": "string"},
        "series_ids": STRING_ARRAY,
        "transforms": STRING_ARRAY,
        "layout": {"type": "string"},
        "y_starts_at_zero": {"type": "boolean"},
        "time_window_rationale": {"type": "string"},
        "annotations": STRING_ARRAY,
        "title": {"type": "string"},
        "x_label": {"type": "string"},
        "y_label": {"type": "string"},
        "units": {"type": "string"},
        "notes": {"type": "string"},
        "chart_type": {"type": "string"},
        "y_left_label": {"type": "string"},
        "y_right_label": {"type": "string"},
    },
    "required": [
        "claim",
        "series_ids",
        "transforms",
        "layout",
        "y_starts_at_zero",
        "time_window_rationale",
        "annotations",
        "title",
        "x_label",
        "y_label",
        "units",
        "notes",
        "chart_type",
        "y_left_label",
        "y_right_label",
    ],
}

DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string"},
        "referenced_metrics": STRING_ARRAY,
        "chart_paths": STRING_ARRAY,
    },
    "required": ["answer", "referenced_metrics", "chart_paths"],
}
