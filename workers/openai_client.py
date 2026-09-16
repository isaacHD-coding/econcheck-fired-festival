"""Small OpenAI Responses API helper for structured worker artifacts."""

from __future__ import annotations

from concurrent.futures import Future, TimeoutError as FuturesTimeoutError
import json
import re
import threading
from typing import Any, Callable, TypeVar

from harness.config import resolve_openai_api_key as _resolve_openai_api_key


DEFAULT_OPENAI_MODEL = "gpt-5.5"
# Harness owns retries. The SDK default (2 retries × 10-minute timeout) made
# Ctrl+C sit on Streamlit "Stopping…" while a blocking HTTP call finished.
# Light stages stay at 30s. Analysis codegen (and chart briefs) get a longer
# hard cap so legitimate structured output is not killed mid-call.
DEFAULT_OPENAI_TIMEOUT_SECONDS = 30.0
OPENAI_PLAN_TIMEOUT_SECONDS = 30.0
OPENAI_SELECT_DATA_TIMEOUT_SECONDS = 30.0
OPENAI_DESIGN_CHART_TIMEOUT_SECONDS = 60.0
OPENAI_WRITE_CODE_TIMEOUT_SECONDS = 120.0
OPENAI_DRAFT_TIMEOUT_SECONDS = 30.0
OPENAI_CHECKER_TIMEOUT_SECONDS = 30.0
DEFAULT_OPENAI_CONNECT_TIMEOUT_SECONDS = 5.0
DEFAULT_OPENAI_MAX_RETRIES = 0

OPENAI_TIMEOUT_SECONDS_BY_STAGE: dict[str, float] = {
    "plan": OPENAI_PLAN_TIMEOUT_SECONDS,
    "select_data": OPENAI_SELECT_DATA_TIMEOUT_SECONDS,
    "design_chart": OPENAI_DESIGN_CHART_TIMEOUT_SECONDS,
    "write_code": OPENAI_WRITE_CODE_TIMEOUT_SECONDS,
    "draft_answer": OPENAI_DRAFT_TIMEOUT_SECONDS,
    "review": OPENAI_CHECKER_TIMEOUT_SECONDS,
}

OPENAI_TIMEOUT_SECONDS_BY_SCHEMA: dict[str, float] = {
    "planner_artifact": OPENAI_PLAN_TIMEOUT_SECONDS,
    "data_selection_artifact": OPENAI_SELECT_DATA_TIMEOUT_SECONDS,
    "chart_brief_artifact": OPENAI_DESIGN_CHART_TIMEOUT_SECONDS,
    "code_artifact": OPENAI_WRITE_CODE_TIMEOUT_SECONDS,
    "draft_artifact": OPENAI_DRAFT_TIMEOUT_SECONDS,
    "checker_artifact": OPENAI_CHECKER_TIMEOUT_SECONDS,
}

_FRIENDLY_STAGE_LABELS = {
    "plan": "Planning",
    "planning": "Planning",
    "planner_artifact": "Planning",
    "select_data": "Data selection",
    "data_discovery": "Data selection",
    "data_selection_artifact": "Data selection",
    "design_chart": "Chart design",
    "chart_brief_artifact": "Chart design",
    "write_code": "Code generation",
    "code_generation": "Code generation",
    "code_artifact": "Code generation",
    "draft_answer": "Drafting the answer",
    "draft_artifact": "Drafting the answer",
    "review": "Review",
    "checker_review": "Review",
    "checker_artifact": "Review",
}

T = TypeVar("T")


class OpenAIClientError(RuntimeError):
    """Raised for OpenAI configuration, SDK, or response-shape failures."""


class OpenAITimeoutError(OpenAIClientError):
    """Raised when the hard timeout fires before the SDK returns."""

    def __init__(
        self,
        schema_name: str,
        timeout_seconds: float,
        *,
        stage_label: str = "",
    ) -> None:
        self.schema_name = schema_name
        self.timeout_seconds = float(timeout_seconds)
        self.stage_label = stage_label or schema_name
        super().__init__(
            f"OpenAI {schema_name} call timed out after {self.timeout_seconds:.0f}s."
        )


def openai_timeout_seconds(
    *,
    schema_name: str | None = None,
    stage_label: str | None = None,
    cap_seconds: float | None = None,
) -> float:
    """Return the hard timeout for an OpenAI stage, optionally capped by remaining run budget."""

    timeout = DEFAULT_OPENAI_TIMEOUT_SECONDS
    if stage_label and stage_label in OPENAI_TIMEOUT_SECONDS_BY_STAGE:
        timeout = OPENAI_TIMEOUT_SECONDS_BY_STAGE[stage_label]
    elif schema_name and schema_name in OPENAI_TIMEOUT_SECONDS_BY_SCHEMA:
        timeout = OPENAI_TIMEOUT_SECONDS_BY_SCHEMA[schema_name]
    if cap_seconds is not None:
        timeout = min(timeout, max(0.1, float(cap_seconds)))
    return timeout


def user_facing_openai_timeout_message(
    stage_or_schema: str,
    timeout_seconds: float,
) -> str:
    """Plain-language timeout copy for alarms and the chat UI."""

    label = _FRIENDLY_STAGE_LABELS.get(stage_or_schema, "This step")
    return (
        f"{label} took longer than {timeout_seconds:.0f} seconds waiting for the "
        "model and was stopped so the run cannot hang."
    )


def openai_timeout_details(exc: BaseException) -> dict[str, Any] | None:
    """Return timeout metadata if ``exc`` (or its cause chain) is an OpenAI timeout."""

    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        timeout_seconds = getattr(current, "timeout_seconds", None)
        if isinstance(current, OpenAITimeoutError) or timeout_seconds is not None:
            stage_label = str(getattr(current, "stage_label", "") or "")
            schema_name = str(getattr(current, "schema_name", "") or "")
            seconds = (
                float(timeout_seconds)
                if timeout_seconds is not None
                else _parse_timeout_seconds(str(current))
            )
            if seconds is None:
                current = current.__cause__ or current.__context__
                continue
            return {
                "timeout_seconds": seconds,
                "stage_label": stage_label,
                "schema_name": schema_name,
                "message": str(current),
            }
        parsed = _parse_timeout_seconds(str(current))
        if parsed is not None and "timed out" in str(current).lower():
            return {
                "timeout_seconds": parsed,
                "stage_label": "",
                "schema_name": "",
                "message": str(current),
            }
        current = current.__cause__ or current.__context__
    return None


def _parse_timeout_seconds(text: str) -> float | None:
    match = re.search(r"timed out after (\d+(?:\.\d+)?)s", text, flags=re.IGNORECASE)
    if match is None:
        return None
    return float(match.group(1))


def resolve_openai_api_key(api_key: str | None) -> str:
    resolved = _resolve_openai_api_key(api_key)
    if not resolved:
        raise OpenAIClientError(
            "OPENAI_API_KEY is not configured. Enter an OpenAI API key or set "
            "OPENAI_API_KEY in your environment, a local .env file, or Streamlit "
            "secrets, then rerun."
        )
    return resolved


def call_openai_json(
    *,
    schema_name: str,
    schema: dict[str, Any],
    instructions: str,
    input_payload: dict[str, Any],
    api_key: str | None = None,
    model: str = DEFAULT_OPENAI_MODEL,
    timeout_seconds: float | None = None,
    max_retries: int = DEFAULT_OPENAI_MAX_RETRIES,
    stage_label: str = "",
) -> dict[str, Any]:
    """Call the Responses API and parse strict structured JSON output."""

    resolved_timeout = (
        float(timeout_seconds)
        if timeout_seconds is not None
        else openai_timeout_seconds(schema_name=schema_name, stage_label=stage_label or None)
    )
    resolved_api_key = resolve_openai_api_key(api_key)
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise OpenAIClientError(
            "The openai package is not installed. Install project dependencies "
            "before using the OpenAI agent."
        ) from exc

    client = OpenAI(
        api_key=resolved_api_key,
        timeout=_sdk_timeout(resolved_timeout),
        max_retries=max_retries,
    )

    def invoke() -> dict[str, Any]:
        try:
            response = client.responses.create(
                model=model,
                input=[
                    {"role": "system", "content": instructions},
                    {
                        "role": "user",
                        "content": json.dumps(input_payload, sort_keys=True),
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    }
                },
            )
        except Exception as exc:
            raise OpenAIClientError(
                f"OpenAI Responses API call failed for {schema_name}: {exc.__class__.__name__}"
            ) from exc

        output_text = _response_output_text(response)
        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise OpenAIClientError(
                f"OpenAI response for {schema_name} was not valid JSON."
            ) from exc

        if not isinstance(parsed, dict):
            raise OpenAIClientError(
                f"OpenAI response for {schema_name} must be a JSON object."
            )
        return parsed

    try:
        return _run_with_hard_timeout(invoke, resolved_timeout)
    except FuturesTimeoutError as exc:
        raise OpenAITimeoutError(
            schema_name,
            resolved_timeout,
            stage_label=stage_label,
        ) from exc


def _response_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    output = getattr(response, "output", None)
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            content = getattr(item, "content", None)
            if isinstance(content, list):
                for content_item in content:
                    text = getattr(content_item, "text", None)
                    if isinstance(text, str):
                        parts.append(text)
                    elif isinstance(content_item, dict) and isinstance(content_item.get("text"), str):
                        parts.append(content_item["text"])
        if parts:
            return "".join(parts)

    raise OpenAIClientError("OpenAI response did not include output_text.")


def _sdk_timeout(timeout_seconds: float) -> Any:
    try:
        from httpx import Timeout
    except Exception:
        return timeout_seconds
    return Timeout(
        timeout_seconds,
        connect=min(DEFAULT_OPENAI_CONNECT_TIMEOUT_SECONDS, timeout_seconds),
        read=timeout_seconds,
        write=min(10.0, timeout_seconds),
        pool=timeout_seconds,
    )


def _run_with_hard_timeout(fn: Callable[[], T], timeout_seconds: float) -> T:
    """Wait on a daemon thread so a stuck HTTP call cannot pin the main thread.

    Streamlit Ctrl+C shows "Stopping…" until the script thread returns. Waiting
    here is interruptible; the SDK socket call is not.
    """

    future: Future[T] = Future()

    def worker() -> None:
        try:
            future.set_result(fn())
        except BaseException as exc:  # noqa: BLE001 — propagate into Future
            if not future.done():
                future.set_exception(exc)

    thread = threading.Thread(target=worker, name="econcheck-openai-call", daemon=True)
    thread.start()
    return future.result(timeout=timeout_seconds)
