"""Small OpenAI Responses API helper for structured worker artifacts."""

from __future__ import annotations

from concurrent.futures import Future, TimeoutError as FuturesTimeoutError
import json
import threading
from typing import Any, Callable, TypeVar

from harness.config import resolve_openai_api_key as _resolve_openai_api_key


DEFAULT_OPENAI_MODEL = "gpt-5.5"
# Harness owns retries. The SDK default (2 retries × 10-minute timeout) made
# Ctrl+C sit on Streamlit "Stopping…" while a blocking HTTP call finished.
DEFAULT_OPENAI_TIMEOUT_SECONDS = 30.0
DEFAULT_OPENAI_CONNECT_TIMEOUT_SECONDS = 5.0
DEFAULT_OPENAI_MAX_RETRIES = 0

T = TypeVar("T")


class OpenAIClientError(RuntimeError):
    """Raised for OpenAI configuration, SDK, or response-shape failures."""


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
    timeout_seconds: float = DEFAULT_OPENAI_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_OPENAI_MAX_RETRIES,
) -> dict[str, Any]:
    """Call the Responses API and parse strict structured JSON output."""

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
        timeout=_sdk_timeout(timeout_seconds),
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
        return _run_with_hard_timeout(invoke, timeout_seconds)
    except FuturesTimeoutError as exc:
        raise OpenAIClientError(
            f"OpenAI {schema_name} call timed out after {timeout_seconds:.0f}s."
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
