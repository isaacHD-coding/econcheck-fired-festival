"""Live FRED Search and Fetch tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from workers.artifacts import DataArtifact


FRED_BASE_URL = "https://api.stlouisfed.org/fred"
DEFAULT_TIMEOUT_SECONDS = 20


class FredConfigurationError(RuntimeError):
    """Raised when live FRED credentials are not configured."""


class FredToolError(RuntimeError):
    """Raised when a live FRED request fails or returns unusable data."""


@dataclass
class SeriesSearchResult:
    series_id: str
    title: str
    frequency: str
    units: str
    observation_start: str
    observation_end: str

    def to_dict(self) -> dict[str, str]:
        return {
            "series_id": self.series_id,
            "title": self.title,
            "frequency": self.frequency,
            "units": self.units,
            "observation_start": self.observation_start,
            "observation_end": self.observation_end,
        }


def fred_search(
    search_text: str,
    *,
    api_key: str | None = None,
    limit: int = 10,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[SeriesSearchResult]:
    """Search FRED for economic series using the live JSON API."""

    api_key = _require_api_key(api_key)
    payload = _request_json(
        "series/search",
        {
            "api_key": api_key,
            "file_type": "json",
            "search_text": search_text,
            "limit": str(limit),
            "order_by": "search_rank",
        },
        timeout_seconds=timeout_seconds,
    )

    return [
        SeriesSearchResult(
            series_id=str(item.get("id", "")),
            title=str(item.get("title", "")),
            frequency=str(item.get("frequency", "")),
            units=str(item.get("units", "")),
            observation_start=str(item.get("observation_start", "")),
            observation_end=str(item.get("observation_end", "")),
        )
        for item in payload.get("seriess", [])
        if item.get("id")
    ]


def fred_fetch(
    series_ids: list[str],
    *,
    api_key: str | None = None,
    observation_start: date | str | None = None,
    observation_end: date | str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> DataArtifact:
    """Fetch observations for selected FRED series using the live JSON API."""

    api_key = _require_api_key(api_key)
    observations: dict[str, list[dict[str, Any]]] = {}
    metadata: dict[str, Any] = {
        "source": "FRED",
        "tool": "fred_fetch",
        "observation_start": _date_string(observation_start),
        "observation_end": _date_string(observation_end),
        "series": {},
    }

    for series_id in series_ids:
        payload = _request_json(
            "series/observations",
            _fetch_params(
                api_key=api_key,
                series_id=series_id,
                observation_start=observation_start,
                observation_end=observation_end,
            ),
            timeout_seconds=timeout_seconds,
        )
        rows = [_observation_to_row(series_id, item) for item in payload.get("observations", [])]
        clean_rows = [row for row in rows if row is not None]
        if not clean_rows:
            raise FredToolError(f"FRED returned no numeric observations for {series_id}.")
        observations[series_id] = clean_rows
        metadata["series"][series_id] = {
            "observation_count": len(clean_rows),
            "first_date": clean_rows[0]["date"],
            "last_date": clean_rows[-1]["date"],
        }

    return DataArtifact(
        series_ids=list(series_ids),
        observations=observations,
        metadata=metadata,
    )


def _fetch_params(
    *,
    api_key: str,
    series_id: str,
    observation_start: date | str | None,
    observation_end: date | str | None,
) -> dict[str, str]:
    params = {
        "api_key": api_key,
        "file_type": "json",
        "series_id": series_id,
    }
    if observation_start is not None:
        params["observation_start"] = _date_string(observation_start)
    if observation_end is not None:
        params["observation_end"] = _date_string(observation_end)
    return params


def _request_json(
    endpoint: str,
    params: dict[str, str],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    url = f"{FRED_BASE_URL}/{endpoint}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "econcheck/0.1"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise FredToolError(f"FRED HTTP {exc.code} for {endpoint}: {body}") from exc
    except URLError as exc:
        raise FredToolError(f"FRED request failed for {endpoint}: {exc.reason}") from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise FredToolError(f"FRED returned invalid JSON for {endpoint}.") from exc

    if "error_code" in payload:
        message = payload.get("error_message", "Unknown FRED error.")
        raise FredToolError(f"FRED error {payload['error_code']}: {message}")
    return payload


def _observation_to_row(series_id: str, item: dict[str, Any]) -> dict[str, Any] | None:
    value = item.get("value")
    if value in (None, "."):
        return None
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return None
    return {
        "series_id": series_id,
        "date": str(item.get("date", "")),
        "value": numeric_value,
    }


def _require_api_key(api_key: str | None) -> str:
    resolved = api_key or os.environ.get("FRED_API_KEY")
    if not resolved:
        raise FredConfigurationError(
            "FRED_API_KEY not configured. "
            "Milestone 17 requires live FRED integration. "
            "Set FRED_API_KEY and rerun."
        )
    return resolved


def _date_string(value: date | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
