"""Data checkpoints for evidence provenance."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from harness.checkpoints.base import CheckpointResult
from harness.domain import is_cpi_question, is_relationship_question


class SourceProvenanceCheckpoint:
    """Require selected FRED series to come from live search, and metrics to cite sources."""

    def evaluate(
        self,
        artifact: Any,
        search_results: list | None = None,
    ) -> CheckpointResult:
        if search_results is not None:
            return self._evaluate_selected_series(artifact, search_results)
        return self._evaluate_metric_sources(artifact)

    def _evaluate_selected_series(
        self,
        selection: Any,
        search_results: list,
    ) -> CheckpointResult:
        selected_ids = _selected_series_ids(selection)
        searched_ids = {
            str(result.get("series_id"))
            for result in search_results
            if isinstance(result, Mapping) and result.get("series_id")
        }
        missing = [series_id for series_id in selected_ids if series_id not in searched_ids]
        if not selected_ids or missing:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="data_discovery",
                message="Selected series must come from live FRED search results.",
                retry_from="data_discovery",
                context={
                    "selected_series": selected_ids,
                    "missing_from_search": missing,
                },
            )
        return CheckpointResult.pass_result(
            "Selected series come from live FRED search results."
        )

    def _evaluate_metric_sources(self, analysis: Any) -> CheckpointResult:
        metrics = _read_field(analysis, "metrics")
        if not isinstance(metrics, list):
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="code_generation",
                message="Analysis metrics are missing or invalid.",
                retry_from="code_generation",
                context={"field": "metrics"},
            )

        missing = [
            _metric_label(metric, index)
            for index, metric in enumerate(metrics)
            if not _has_field(metric, "source_series")
        ]
        if missing:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="code_generation",
                message="One or more metrics are missing source_series provenance.",
                retry_from="code_generation",
                context={"missing_metrics": missing},
            )

        return CheckpointResult.pass_result(
            "Every metric includes source_series provenance."
        )


class DataCompletenessCheckpoint:
    """Require enough numeric observations to support a trend analysis."""

    def evaluate(
        self,
        artifact: Any,
        selected_series: list | None = None,
    ) -> CheckpointResult:
        observations = _read_field(artifact, "observations")
        if not isinstance(observations, dict):
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="data_discovery",
                message="Fetched FRED observations are missing or invalid.",
                retry_from="data_discovery",
                context={"field": "observations"},
            )

        selected_ids = _selected_series_ids(selected_series) if selected_series else list(
            _read_field(artifact, "series_ids") or observations
        )
        counts = {
            series_id: len(observations.get(series_id, []))
            for series_id in selected_ids
        }
        frequency_by_id = _frequencies(selected_series)
        failed = [
            series_id
            for series_id, count in counts.items()
            if count < _minimum_observations(series_id, frequency_by_id.get(series_id, ""))
        ]
        if not counts or failed:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="data_discovery",
                message="Selected series do not include enough numeric observations.",
                retry_from="data_discovery",
                context={"observation_counts": counts, "failed_series": failed},
            )

        return CheckpointResult.pass_result(
            "Selected series include enough numeric observations."
        )


class FreshnessCheckpoint:
    """Require latest observations to fall within a normal release-lag window."""

    def evaluate(self, artifact: Any, selected_ids: list[str] | None = None) -> CheckpointResult:
        observations = _read_field(artifact, "observations")
        if not isinstance(observations, dict):
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="data_discovery",
                message="Fetched FRED observations are missing or invalid.",
                retry_from="data_discovery",
                context={"field": "observations"},
            )

        ids = selected_ids or list(_read_field(artifact, "series_ids") or observations)
        latest_dates = {
            series_id: _latest_observation_date(observations.get(series_id, []))
            for series_id in ids
        }
        stale = [
            series_id
            for series_id, latest in latest_dates.items()
            if latest is None or (date.today() - latest).days > 180
        ]
        if not latest_dates or stale:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="data_discovery",
                message="Latest observations are missing or older than the allowed release lag.",
                retry_from="data_discovery",
                context={
                    "latest_dates": {
                        series_id: latest.isoformat() if latest is not None else None
                        for series_id, latest in latest_dates.items()
                    },
                    "stale_series": stale,
                },
            )

        return CheckpointResult.pass_result(
            "Latest observations are within a normal release-lag window."
        )


class InformationSufficiencyCheckpoint:
    """Require enough evidence to answer the submitted question."""

    def evaluate(
        self,
        artifact: Any,
        selected_ids: list[str] | None = None,
        question: str = "",
    ) -> CheckpointResult:
        observations = _read_field(artifact, "observations")
        series_ids = list(_read_field(artifact, "series_ids") or [])
        ids = selected_ids or series_ids
        if not isinstance(observations, dict):
            observations = {}

        if is_cpi_question(question):
            passed = "CPIAUCSL" in ids and bool(observations.get("CPIAUCSL"))
            message = "CPIAUCSL observations are required for CPI/inflation questions."
        elif is_relationship_question(question):
            present = [series_id for series_id in ids if observations.get(series_id)]
            passed = len(present) >= 2
            message = "Relationship questions require at least two fetched FRED series."
        else:
            passed = bool(ids) and all(observations.get(series_id) for series_id in ids)
            message = "Selected FRED series must include fetched observations."

        if not passed:
            return CheckpointResult.fail_result(
                checkpoint_name=self.__class__.__name__,
                stage="data_discovery",
                message=message,
                retry_from="data_discovery",
                context={"selected_series": ids, "question": question},
            )

        return CheckpointResult.pass_result("Selected evidence is sufficient to continue.")


def _selected_series_ids(selection: Any) -> list[str]:
    if selection is None:
        return []
    if isinstance(selection, list):
        items = selection
    else:
        items = _read_field(selection, "selected_series") or []
    ids: list[str] = []
    for item in items:
        series_id = _read_field(item, "series_id") if not isinstance(item, str) else item
        if isinstance(series_id, str) and series_id:
            ids.append(series_id)
    return ids


def _frequencies(selected_series: list | None) -> dict[str, str]:
    frequencies: dict[str, str] = {}
    for item in selected_series or []:
        if not isinstance(item, Mapping):
            continue
        series_id = item.get("series_id")
        if isinstance(series_id, str) and series_id:
            frequencies[series_id] = str(item.get("frequency") or "")
    return frequencies


def _minimum_observations(series_id: str, frequency: str) -> int:
    text = frequency.lower()
    if "annual" in text or "yearly" in text:
        return 5
    if "quarter" in text:
        return 16
    if "weekly" in text or "daily" in text:
        return 48
    if "monthly" in text or series_id == "CPIAUCSL":
        return 48
    return 8


def _latest_observation_date(rows: list[Any]) -> date | None:
    if not rows:
        return None
    last = rows[-1]
    raw = _read_field(last, "date") if not isinstance(last, str) else last
    try:
        return datetime.strptime(str(raw), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _read_field(artifact: Any, field_name: str) -> Any:
    if isinstance(artifact, Mapping):
        return artifact.get(field_name)
    return getattr(artifact, field_name, None)


def _has_field(item: Any, field_name: str) -> bool:
    if isinstance(item, Mapping):
        return field_name in item
    return hasattr(item, field_name)


def _metric_label(metric: Any, index: int) -> str:
    name = _read_field(metric, "name")
    if isinstance(name, str) and name:
        return name
    return f"metric[{index}]"
