from dataclasses import dataclass
from typing import Any

import pytest

from harness.tools.code_runner import run_analysis_code
from workers.artifacts import AnalysisArtifact, CodeArtifact


@dataclass
class _DataArtifact:
    series_ids: list[str]
    observations: dict[str, list[dict[str, Any]]]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "series_ids": list(self.series_ids),
            "observations": {
                series_id: list(rows)
                for series_id, rows in self.observations.items()
            },
            "metadata": dict(self.metadata),
        }


def _data_artifact() -> _DataArtifact:
    return _DataArtifact(
        series_ids=["CPIAUCSL"],
        observations={
            "CPIAUCSL": [
                {"series_id": "CPIAUCSL", "date": "2024-01-01", "value": 308.417},
                {"series_id": "CPIAUCSL", "date": "2024-02-01", "value": 310.326},
            ]
        },
        metadata={"source": "FRED"},
    )


def test_code_runner_executes_valid_code():
    code_artifact = CodeArtifact(
        code="""
analysis_output = {
    "tables": [],
    "metrics": [],
    "claims": [],
    "charts": [],
    "method_notes": "generated code ran",
    "warnings": [],
}
"""
    )

    analysis = run_analysis_code(code_artifact, _data_artifact())

    assert isinstance(analysis, AnalysisArtifact)
    assert analysis.method_notes == "generated code ran"


def test_code_runner_enforces_timeout():
    code_artifact = CodeArtifact(
        code="""
while True:
    pass
"""
    )

    with pytest.raises(TimeoutError, match="timed out"):
        run_analysis_code(
            code_artifact,
            _data_artifact(),
            timeout_seconds=0.2,
        )


def test_code_runner_produces_output_artifact():
    expected_metric = {
        "name": "latest_cpi",
        "value": 310.326,
        "unit": "index",
        "source_series": ["CPIAUCSL"],
    }
    code_artifact = CodeArtifact(
        code=f"""
analysis_output = {{
    "tables": [
        {{"name": "latest_values", "rows": input_data["observations"]["CPIAUCSL"]}}
    ],
    "metrics": [{expected_metric!r}],
    "claims": [
        {{"text": "CPI reached 310.326.", "metric_refs": ["latest_cpi"]}}
    ],
    "charts": [],
    "method_notes": "Used the latest available observation.",
    "warnings": [],
}}
"""
    )

    analysis = run_analysis_code(code_artifact, _data_artifact())

    assert analysis == AnalysisArtifact(
        tables=[
            {
                "name": "latest_values",
                "rows": _data_artifact().observations["CPIAUCSL"],
            }
        ],
        metrics=[expected_metric],
        claims=[{"text": "CPI reached 310.326.", "metric_refs": ["latest_cpi"]}],
        charts=[],
        method_notes="Used the latest available observation.",
        warnings=[],
    )


def test_code_runner_receives_input_data():
    code_artifact = CodeArtifact(
        code="""
latest_row = input_data["observations"]["CPIAUCSL"][-1]
analysis_output = {
    "tables": [],
    "metrics": [
        {
            "name": "latest_value",
            "value": latest_row["value"],
            "unit": "index",
            "source_series": input_data["series_ids"],
        }
    ],
    "claims": [],
    "charts": [],
    "method_notes": f"Read {latest_row['date']} from input_data.",
    "warnings": [],
}
"""
    )

    analysis = run_analysis_code(code_artifact, _data_artifact())

    assert analysis.metrics == [
        {
            "name": "latest_value",
            "value": 310.326,
            "unit": "index",
            "source_series": ["CPIAUCSL"],
        }
    ]
    assert analysis.method_notes == "Read 2024-02-01 from input_data."
