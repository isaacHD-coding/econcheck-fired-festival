"""Small OpenAI Responses API helper for structured worker artifacts."""

from __future__ import annotations

import json
import os
from typing import Any


DEFAULT_OPENAI_MODEL = "gpt-5.5"


class OpenAIClientError(RuntimeError):
    """Raised for OpenAI configuration, SDK, or response-shape failures."""


def resolve_openai_api_key(api_key: str | None) -> str:
    resolved = (api_key or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    if not resolved:
        raise OpenAIClientError(
            "OPENAI_API_KEY not configured. Enter an OpenAI API key or set "
            "OPENAI_API_KEY and rerun."
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

    client = OpenAI(api_key=resolved_api_key)
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
