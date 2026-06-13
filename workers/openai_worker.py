"""OpenAI-backed EconCheck worker implementation."""

from __future__ import annotations

import json
from typing import Any, TypeVar

from harness.state import RunState
from workers.artifacts import (
    AnalysisArtifact,
    ArtifactValidationError,
    CodeArtifact,
    DataArtifact,
    DataSelectionArtifact,
    DraftArtifact,
    PlannerArtifact,
)
from workers.openai_client import DEFAULT_OPENAI_MODEL, OpenAIClientError, call_openai_json


class OpenAIWorkerError(RuntimeError):
    """Raised when a model artifact cannot be accepted by the harness."""


ArtifactT = TypeVar(
    "ArtifactT",
    PlannerArtifact,
    DataSelectionArtifact,
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

    def plan(self, question: str, state: RunState) -> PlannerArtifact:
        payload = {
            "question": question,
            "state": state.to_dict(),
        }
        return self._call_artifact(
            schema_name="planner_artifact",
            schema=PLANNER_SCHEMA,
            instructions=_stage_instructions(
                "Planning",
                "Create a concise economic analysis plan for the user's question.",
                (
                    "For the canonical CPI demo, prefer a FRED search query that can "
                    "find CPIAUCSL, the all-items CPI for all urban consumers."
                ),
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
        return self._call_artifact(
            schema_name="data_selection_artifact",
            schema=DATA_SELECTION_SCHEMA,
            instructions=_stage_instructions(
                "Data selection",
                "Select the FRED series that best satisfies the plan using only the provided search results.",
                (
                    "For the canonical CPI demo, select CPIAUCSL when it appears. "
                    "Do not invent series that are absent from the search results."
                ),
            ),
            input_payload=payload,
            artifact_cls=DataSelectionArtifact,
            stage_label="select_data",
        )

    def write_code(
        self,
        plan: PlannerArtifact,
        data_summary: DataArtifact,
    ) -> CodeArtifact:
        payload = {
            "plan": plan.to_dict(),
            "data": data_summary.to_dict(),
        }
        return self._call_artifact(
            schema_name="code_artifact",
            schema=CODE_SCHEMA,
            instructions=_stage_instructions(
                "Code generation",
                "Write complete Python analysis code for the supplied DataArtifact.",
                (
                    "Return Python only in the JSON code field. The code must assign "
                    "analysis_output as a dict with tables, metrics, claims, charts, "
                    "method_notes, and warnings. Use only input_data. Do not call FRED, "
                    "do not use the network, do not use subprocesses, do not install "
                    "packages, and do not read or write files. Use only the Python "
                    "standard library."
                ),
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
        return self._call_artifact(
            schema_name="draft_artifact",
            schema=DRAFT_SCHEMA,
            instructions=_stage_instructions(
                "Draft answer",
                "Draft the user-facing answer using only the provided AnalysisArtifact.",
                (
                    "Do not invent numbers. Cite generated metric names in "
                    "referenced_metrics. Include chart references from analysis.charts "
                    "as analysis.json#charts/{index} when charts are available."
                ),
            ),
            input_payload=payload,
            artifact_cls=DraftArtifact,
            stage_label="draft_answer",
        )

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


HARNESS_BOUNDARY_RULES = (
    "Harness boundary rules: you are the worker only. You may plan, select data, "
    "write code, and draft answers. You may not call FRED, fetch data, execute code, "
    "route retries, escalate failures, or release answers. The harness owns tools, "
    "execution, checkpoints, alarms, persistence, observability, and release."
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
