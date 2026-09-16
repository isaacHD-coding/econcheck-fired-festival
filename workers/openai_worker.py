"""OpenAI-backed EconCheck worker implementation."""

from __future__ import annotations

import json
from typing import Any, TypeVar

from harness.domain import (
    is_canonical_cpi_demo_question,
    is_comparison_question,
    is_relationship_question,
    plan_requests_relationship,
    wanted_series_for_question,
)
from harness.state import RunState
from workers.analysis_templates import (
    canonical_cpi_analysis_code,
    canonical_cpi_draft,
    comparison_analysis_code,
    comparison_draft,
    draft_uses_plain_series_names,
    looks_like_canned_cpi_draft,
    looks_like_jargony_relationship_draft,
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
from workers.chart_briefs import build_chart_brief, repair_chart_brief
from workers.openai_client import (
    DEFAULT_OPENAI_MODEL,
    OpenAIClientError,
    OpenAITimeoutError,
    call_openai_json,
    openai_timeout_seconds,
    user_facing_openai_timeout_message,
)


class OpenAIWorkerError(RuntimeError):
    """Raised when a model artifact cannot be accepted by the harness."""


class OpenAIWorkerTimeoutError(OpenAIWorkerError):
    """Raised when an OpenAI worker stage hits its hard timeout."""

    def __init__(
        self,
        stage_label: str,
        timeout_seconds: float,
        *,
        schema_name: str = "",
    ) -> None:
        self.stage_label = stage_label
        self.timeout_seconds = float(timeout_seconds)
        self.schema_name = schema_name
        super().__init__(
            user_facing_openai_timeout_message(stage_label or schema_name, self.timeout_seconds)
        )


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
        self._call_timeout_cap_seconds: float | None = None

    def set_call_timeout_cap(self, seconds: float | None) -> None:
        """Cap the next OpenAI call so it cannot outlive remaining run budget."""

        if seconds is None:
            self._call_timeout_cap_seconds = None
            return
        self._call_timeout_cap_seconds = max(0.1, float(seconds))

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
            "question into a CPI-only five-year trend. If it compares CPI and PCE "
            "inflation, plan CPIAUCSL and PCEPI and the year-over-year gap—not a "
            "CPI-only trend and not a GDP correlation. If it compares last year's and "
            "this year's GDP growth, plan one GDP series (GDPC1) and year-over-year "
            "growth versus its one-year lag—do not invent a second series. The "
            "canonical CPI demo question may prefer a query that can find CPIAUCSL. "
            "Charting is a later worker step: the plan should name the claim a chart "
            "must support, not dump every fetched series onto one axis."
        )
        plan = self._call_artifact(
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
        return _ensure_known_plan_queries(plan, question)

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
        if _needs_multi_series_analysis(self.question, plan, None) and selection.selected_series:
            selection = _ensure_search_backed_series(
                selection,
                search_results,
                _wanted_series(self.question, plan, search_results),
            )
        if not selection.selected_series or _missing_wanted_series(
            selection, self.question, plan, search_results
        ):
            if _needs_multi_series_analysis(self.question, plan, None):
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
        # Chart design is harness-deterministic. An extra OpenAI round-trip here
        # stacked on write_code and routinely exhausted the 3-minute run budget.
        return repair_chart_brief(fallback, plan, data_summary, question=self.question)

    def write_code(
        self,
        plan: PlannerArtifact,
        data_summary: DataArtifact,
        chart_brief: ChartBriefArtifact | None = None,
    ) -> CodeArtifact:
        brief = chart_brief or build_chart_brief(plan, data_summary, question=self.question)
        retry_meta: dict[str, Any] = {}
        if hasattr(data_summary, "metadata") and isinstance(data_summary.metadata, dict):
            data_summary.metadata["chart_brief"] = brief.to_dict()
            raw_retry = data_summary.metadata.get("codegen_retry") or {}
            if isinstance(raw_retry, dict):
                retry_meta = raw_retry
        template = _analysis_code_template(self.question, plan, data_summary)
        if template is not None:
            return CodeArtifact(code=template)
        extra = WRITE_CODE_GUIDANCE
        if retry_meta:
            extra = SIMPLE_RETRY_WRITE_CODE_GUIDANCE + "\n" + WRITE_CODE_GUIDANCE
        payload = {
            "plan": plan.to_dict(),
            "data": _compact_data_payload(data_summary),
            "chart_brief": brief.to_dict(),
            "codegen_constraints": {
                "max_lines": 120,
                "max_helpers": 4,
                "one_chart": True,
                "follow_chart_brief": True,
                "price_index_comparison": "yoy_percent_and_gap_only",
                "metrics_schema": (
                    "list of {name: str, value: number, unit: str, source_series: [FRED ids]}"
                ),
                "charts_schema": (
                    "non-empty list of {type, title, x_field, y_field, series_ids, "
                    "unit, data: [{date, ...y fields}]}"
                ),
            },
        }
        if retry_meta:
            payload["codegen_retry"] = retry_meta
        return self._call_artifact(
            schema_name="code_artifact",
            schema=CODE_SCHEMA,
            instructions=_stage_instructions(
                "Code generation",
                "Write a short Python analysis script for the supplied DataArtifact.",
                extra,
            ),
            input_payload=payload,
            artifact_cls=CodeArtifact,
            stage_label="write_code",
        )

    def draft_answer(
        self,
        plan: PlannerArtifact,
        analysis: AnalysisArtifact,
    ) -> DraftArtifact:
        payload = {
            "plan": plan.to_dict(),
            "analysis": analysis.to_dict(),
        }
        templated = _draft_template(self.question, plan, analysis)
        if templated is not None:
            return templated
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
                    "do not replace it with a CPI-only five-year paragraph. "
                    "Write for a non-specialist: lead with the result in one clear "
                    "sentence (what moved together or opposite, and the correlation). "
                    "Immediately explain the series in plain English with FRED ids in "
                    "parentheses once (CPI all items / real GDP). Then one short method "
                    "clause (aligned period-over-period growth, n periods) and one short "
                    "caveat (not causal; not a full lead-lag study). Do not open with "
                    "jargon such as contemporaneous association or lead-lag."
                ),
            ),
            input_payload=payload,
            artifact_cls=DraftArtifact,
            stage_label="draft_answer",
        )
        if _allow_canonical_cpi_fallback(self.question, plan, analysis) and _is_canonical_cpi_analysis(analysis):
            return canonical_cpi_draft(analysis)
        if _is_relationship_analysis(analysis) and (
            looks_like_canned_cpi_draft(draft)
            or not _draft_mentions_relationship(draft)
            or looks_like_jargony_relationship_draft(draft)
            or not draft_uses_plain_series_names(draft, analysis)
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
        timeout_seconds = openai_timeout_seconds(
            schema_name=schema_name,
            stage_label=stage_label,
            cap_seconds=self._call_timeout_cap_seconds,
        )
        try:
            data = call_openai_json(
                schema_name=schema_name,
                schema=schema,
                instructions=instructions,
                input_payload=input_payload,
                api_key=self.api_key,
                model=self.model,
                timeout_seconds=timeout_seconds,
                stage_label=stage_label,
            )
            return artifact_cls.from_dict(data)
        except OpenAITimeoutError as exc:
            raise OpenAIWorkerTimeoutError(
                stage_label,
                exc.timeout_seconds,
                schema_name=schema_name,
            ) from exc
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
    wanted = _wanted_series(question, plan, search_results)
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


def _ensure_known_plan_queries(plan: PlannerArtifact, question: str) -> PlannerArtifact:
    wanted = wanted_series_for_question(question)
    if not wanted:
        return plan
    queries = list(plan.search_queries)
    blob = " ".join(queries).lower()
    extras = {
        "CPIAUCSL": "Consumer Price Index All Urban Consumers CPIAUCSL",
        "PCEPI": "Personal Consumption Expenditures Chain-type Price Index PCEPI",
        "GDPC1": "Real Gross Domestic Product GDPC1",
    }
    changed = False
    for series_id in wanted:
        token = series_id.lower()
        if token not in blob and series_id in extras:
            queries.append(extras[series_id])
            blob = " ".join(queries).lower()
            changed = True
    if not changed:
        return plan
    payload = plan.to_dict()
    payload["search_queries"] = queries
    return PlannerArtifact.from_dict(payload)


def _analysis_code_template(question: str, plan: Any, data: Any) -> str | None:
    series_ids = _series_ids(data)
    if _allow_canonical_cpi_fallback(question, plan, data):
        return canonical_cpi_analysis_code()
    if _needs_comparison_analysis(question, plan, data) and len(series_ids) >= 2:
        return comparison_analysis_code()
    if len(series_ids) >= 2:
        return relationship_analysis_code()
    return None


def _draft_template(question: str, plan: Any, analysis: AnalysisArtifact) -> DraftArtifact | None:
    if _is_comparison_analysis(analysis) or _needs_comparison_analysis(question, plan, analysis):
        if _is_comparison_analysis(analysis):
            return comparison_draft(analysis)
    if _allow_canonical_cpi_fallback(question, plan, analysis) and _is_canonical_cpi_analysis(analysis):
        return canonical_cpi_draft(analysis)
    if _is_relationship_analysis(analysis):
        return relationship_draft(analysis)
    return None


def _compact_data_payload(data: Any) -> dict[str, Any]:
    """Send series metadata and a few sample rows, not five years of observations."""

    if hasattr(data, "to_dict"):
        raw = data.to_dict()
    elif isinstance(data, dict):
        raw = dict(data)
    else:
        raw = {}
    observations = raw.get("observations") or {}
    summaries: dict[str, Any] = {}
    if isinstance(observations, dict):
        for series_id, rows in observations.items():
            if not isinstance(rows, list):
                continue
            ordered = sorted(
                [row for row in rows if isinstance(row, dict)],
                key=lambda row: str(row.get("date") or ""),
            )
            summaries[str(series_id)] = {
                "n": len(ordered),
                "start": ordered[0].get("date") if ordered else None,
                "end": ordered[-1].get("date") if ordered else None,
                "head": ordered[:2],
                "tail": ordered[-2:],
            }
    metadata = dict(raw.get("metadata") or {})
    metadata.pop("selected_series", None)
    return {
        "series_ids": list(raw.get("series_ids") or summaries),
        "series_summaries": summaries,
        "metadata": metadata,
        "note": (
            "Full observations are available at execution time as input_data. "
            "Do not copy observation rows into generated code."
        ),
    }


def _wanted_series(question: str, plan: PlannerArtifact, search_results: list) -> list[str]:
    text = f"{question} {_plan_blob(plan)}".lower()
    normalized = _normalize_search_results(search_results)
    searched_ids = [str(item.get("series_id")) for item in normalized if item.get("series_id")]
    wanted: list[str] = []
    for series_id in wanted_series_for_question(question):
        if series_id in searched_ids:
            wanted.append(series_id)
    if "CPIAUCSL" in searched_ids and "CPIAUCSL" not in wanted and (
        "inflation" in text or "cpi" in text or "cpiaucsl" in text
    ):
        wanted.append("CPIAUCSL")
    if "PCEPI" in searched_ids and ("pce" in text or "pcepi" in text or "personal consumption" in text):
        if "PCEPI" not in wanted:
            wanted.append("PCEPI")
    if "GDPC1" in searched_ids and "GDPC1" not in wanted and (
        "gdp" in text or "gdpc1" in text or "gross domestic" in text
    ):
        wanted.append("GDPC1")
    for series_id in searched_ids:
        if series_id not in wanted and series_id.lower() in text:
            wanted.append(series_id)
    return wanted


def _missing_wanted_series(
    selection: DataSelectionArtifact,
    question: str,
    plan: PlannerArtifact,
    search_results: list,
) -> bool:
    wanted = _wanted_series(question, plan, search_results)
    if len(wanted) < 2:
        return False
    selected_ids = {item.get("series_id") for item in selection.selected_series}
    return any(series_id not in selected_ids for series_id in wanted)


def _allow_canonical_cpi_selection_recovery(question: str, plan: Any) -> bool:
    if (
        is_comparison_question(question)
        or is_relationship_question(question)
        or plan_requests_relationship(plan)
    ):
        return False
    return not question or is_canonical_cpi_demo_question(question)


def _allow_canonical_cpi_fallback(question: str, plan: Any, data_or_search: Any) -> bool:
    if (
        is_comparison_question(question)
        or is_relationship_question(question)
        or plan_requests_relationship(plan)
    ):
        return False
    series_ids = _series_ids(data_or_search)
    if len(series_ids) > 1:
        return False
    if question and not is_canonical_cpi_demo_question(question):
        return False
    if series_ids and set(series_ids) != {"CPIAUCSL"}:
        return False
    return True


def _needs_multi_series_analysis(question: str, plan: Any, data: Any) -> bool:
    if _needs_comparison_analysis(question, plan, data):
        return True
    return _needs_relationship_analysis(question, plan, data)


def _needs_comparison_analysis(question: str, plan: Any, data: Any) -> bool:
    if is_comparison_question(question):
        return True
    blob = _plan_blob(plan).lower() if plan is not None else ""
    if "pce" in blob or "pcepi" in blob:
        return True
    series_ids = set(_series_ids(data))
    return {"CPIAUCSL", "PCEPI"} <= series_ids


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
    }.issubset(metric_names) and "growth_correlation" not in metric_names and (
        "latest_inflation_gap_percent" not in metric_names
    )


def _is_comparison_analysis(analysis: AnalysisArtifact) -> bool:
    metric_names = {
        metric.get("name")
        for metric in analysis.metrics
        if isinstance(metric, dict) and isinstance(metric.get("name"), str)
    }
    return "latest_inflation_gap_percent" in metric_names


def _is_relationship_analysis(analysis: AnalysisArtifact) -> bool:
    metric_names = {
        metric.get("name")
        for metric in analysis.metrics
        if isinstance(metric, dict) and isinstance(metric.get("name"), str)
    }
    if "growth_correlation" in metric_names:
        return True
    if "latest_inflation_gap_percent" in metric_names:
        return False
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

WRITE_CODE_GUIDANCE = (
    "Keep generated code under 80-120 lines. Prefer a short claim-focused script "
    "that computes the few metrics the question needs plus one clear chart. Do not "
    "write a general-purpose statistics library.\n"
    "Hard limits: do not define many helpers (prefer 0-3 small functions; inline "
    "the rest). Reuse the supplied chart_brief for layout, transforms, title, "
    "labels, and notes. Do not re-implement date-alignment frameworks or restate "
    "design_notes in the generated program.\n"
    "For two monthly price indexes comparing inflation (for example CPI vs PCE / "
    "CPIAUCSL vs PCEPI): compute year-over-year percent change for each series and "
    "the inflation gap. Name the average gap after the actual overlapping YoY "
    "window; do not call it a five-year average unless that window has at least "
    "60 months. YoY MUST be calendar-grounded: for month M use the "
    "observation in the same calendar month 12 months earlier via YYYY-MM date "
    "keys, never a positional 12-row shift. Drop any month that lacks both the "
    "current and prior-year observation for that series; inner-join the two YoY "
    "series on remaining dates. Do not LOCF a shorter series onto a later month "
    "(if PCEPI ends 2026-07, do not emit a 2026-08 PCE YoY). Do not add Pearson "
    "correlation, median/mean batteries, missing-month audit tables, sampled-row "
    "tables, or extra charts unless the question asked for them.\n"
    "Assign analysis_output as a dict that matches the harness AnalysisArtifact "
    "exactly. Top-level keys: tables (list), metrics (list), claims (list), "
    "charts (list), method_notes (string), warnings (list).\n"
    "Each metrics[] item MUST be "
    "{name: str, value: number (not a string), unit: str, source_series: [FRED ids]}. "
    "MathSanity reads metric['value'] as an int or float; nested stats or string "
    "values yield empty metric_values and fail.\n"
    "charts MUST be a non-empty list of chart descriptors. Each chart MUST be "
    "{type: 'line'|'scatter'|'bars'|'panels', title: str, x_field: 'date', "
    "y_field: str or [str], series_ids: [FRED ids], unit: str, "
    "data: [{date: 'YYYY-MM-DD', <y_field>: number, ...}], notes: short caption}. "
    "Do NOT use nested charts[].series objects. Do NOT leave charts empty. "
    "ChartPromise requires a data array of dated rows.\n"
    "Minimal two-index inflation example:\n"
    "metrics = [\n"
    "  {name: 'latest_left_yoy_percent', value: 3.1, unit: 'percent', "
    "source_series: ['CPIAUCSL']},\n"
    "  {name: 'latest_right_yoy_percent', value: 2.8, unit: 'percent', "
    "source_series: ['PCEPI']},\n"
    "  {name: 'latest_inflation_gap_percent', value: 0.3, unit: 'percentage points', "
    "source_series: ['CPIAUCSL', 'PCEPI']}\n"
    "]\n"
    "charts = [{type: 'line', title: 'CPI inflation vs PCE inflation', "
    "x_field: 'date', y_field: ['CPIAUCSL_yoy', 'PCEPI_yoy'], "
    "series_ids: ['CPIAUCSL', 'PCEPI'], unit: 'percent', "
    "data: [{date: '2025-01-01', CPIAUCSL_yoy: 3.1, PCEPI_yoy: 2.8}]}]\n"
    "Return Python only in the JSON code field. Use only input_data. Do not "
    "call FRED, do not use the network, do not use subprocesses, do not install "
    "packages, and do not read or write files. Use only the Python standard library. "
    "If input_data contains more than one series, answer the user's actual question "
    "about those series instead of a CPI-only five-year trend. If the question is "
    "last year's vs this year's GDP growth and only one GDP series is present, "
    "compare year-over-year growth with a one-year lag of the same series.\n"
    "Follow chart_brief. User-facing chart titles, legends, and notes must be plain "
    "English ('CPI growth', 'Real GDP growth', 'PCE inflation'). Chart notes are a "
    "short caption (units, alignment, n) only. Never put 'Do not…' harness design "
    "rules in analysis.charts notes."
)

SIMPLE_RETRY_WRITE_CODE_GUIDANCE = (
    "RETRY: the previous analysis_output failed MathSanity, ChartPromise, or "
    "checker review (often misaligned YoY). Do not write another open-ended novel. "
    "Emit a MINIMAL calendar-YoY+gap script: for each month M, divide by the same "
    "calendar month last year (date keys), drop months missing either observation, "
    "inner-join dates, numeric metric values, and one chart matching schema X "
    "(type/title/x_field/y_field/series_ids/unit/data rows). Keep under 80 lines. "
    "No nested charts[].series, no Pearson, no positional 12-lag, no LOCF past the "
    "last raw month of a series."
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
        "design_notes": {"type": "string"},
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
        "design_notes",
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
