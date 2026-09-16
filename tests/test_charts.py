import pytest

from harness.charts import (
    normalize_analysis_charts,
    normalize_chart,
    shares_single_axis,
    would_dwarf_a_series,
    y_fields,
)
from harness.tools.code_runner import run_analysis_code
from workers.analysis_templates import relationship_analysis_code
from workers.artifacts import AnalysisArtifact, CodeArtifact, DataArtifact


def test_incompatible_level_overlay_is_marked_dual_axis() -> None:
    chart = {
        "type": "line",
        "title": "CPIAUCSL and GDPC1 over the overlapping window",
        "x_field": "date",
        "y_field": ["CPIAUCSL", "GDPC1"],
        "data": [
            {"date": "2021-01-01", "CPIAUCSL": 260.0, "GDPC1": 19000.0},
            {"date": "2022-01-01", "CPIAUCSL": 280.0, "GDPC1": 20000.0},
            {"date": "2023-01-01", "CPIAUCSL": 300.0, "GDPC1": 21000.0},
        ],
    }

    assert would_dwarf_a_series(chart) is True
    normalized = normalize_chart(chart)

    assert normalized["layout"] == "dual_axis"
    assert normalized["shared_y_axis"] is False
    assert normalized["y_left"] == "CPIAUCSL"
    assert normalized["y_right"] == "GDPC1"
    assert shares_single_axis(normalized) is False
    assert would_dwarf_a_series(normalized) is False


def test_growth_rate_overlay_keeps_shared_percent_axis() -> None:
    chart = {
        "type": "line",
        "title": "Period-over-period growth in CPIAUCSL and GDPC1",
        "x_field": "date",
        "y_field": ["CPIAUCSL_growth", "GDPC1_growth"],
        "unit": "percent",
        "data": [
            {"date": "2021-04-01", "CPIAUCSL_growth": 1.2, "GDPC1_growth": 0.4},
            {"date": "2021-07-01", "CPIAUCSL_growth": 0.8, "GDPC1_growth": -0.2},
        ],
    }

    normalized = normalize_chart(chart)
    assert normalized["layout"] == "single"
    assert normalized["shared_y_axis"] is True
    assert would_dwarf_a_series(normalized) is False


def test_relationship_template_does_not_crush_cpi_under_gdp_levels() -> None:
    analysis = run_analysis_code(
        CodeArtifact(code=relationship_analysis_code()),
        _cpi_and_gdp_data(),
    )
    analysis = normalize_analysis_charts(analysis)
    primary = analysis.charts[0]

    fields = set(y_fields(primary))
    assert not (fields >= {"CPIAUCSL", "GDPC1"} and primary.get("layout") == "single")
    assert primary.get("shared_y_axis") is not True or "percent" in str(primary.get("unit", "")).lower() or any(
        "growth" in field for field in fields
    )
    assert would_dwarf_a_series(primary) is False
    assert any("growth" in field for field in fields) or primary.get("layout") == "dual_axis"


def test_normalize_analysis_charts_rewrites_dwarfing_overlay() -> None:
    analysis = AnalysisArtifact(
        tables=[],
        metrics=[{"name": "growth_correlation", "value": -0.4, "unit": "correlation", "source_series": ["CPIAUCSL", "GDPC1"]}],
        claims=[],
        charts=[
            {
                "type": "line",
                "y_field": ["CPIAUCSL", "GDPC1"],
                "data": [
                    {"date": "2021-01-01", "CPIAUCSL": 270.0, "GDPC1": 22000.0},
                    {"date": "2022-01-01", "CPIAUCSL": 290.0, "GDPC1": 23000.0},
                ],
            }
        ],
        method_notes="test",
        warnings=[],
    )

    rewritten = normalize_analysis_charts(analysis).charts[0]
    assert rewritten["layout"] == "dual_axis"
    assert rewritten["shared_y_axis"] is False


def test_render_charts_does_not_plot_incompatible_series_on_one_axis() -> None:
    from harness.charts import render_charts

    class FakeST:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def markdown(self, *args, **kwargs) -> None:
            self.calls.append(("markdown", args, kwargs))

        def caption(self, *args, **kwargs) -> None:
            self.calls.append(("caption", args, kwargs))

        def line_chart(self, *args, **kwargs) -> None:
            self.calls.append(("line_chart", args, kwargs))

        def altair_chart(self, *args, **kwargs) -> None:
            self.calls.append(("altair_chart", args, kwargs))

        def expander(self, *args, **kwargs):
            from contextlib import contextmanager

            @contextmanager
            def _cm():
                yield self

            return _cm()

        def json(self, *args, **kwargs) -> None:
            self.calls.append(("json", args, kwargs))

        def info(self, *args, **kwargs) -> None:
            self.calls.append(("info", args, kwargs))

    chart = {
        "type": "line",
        "title": "CPI vs GDP",
        "x_field": "date",
        "y_field": ["CPIAUCSL", "GDPC1"],
        "data": [
            {"date": "2021-01-01", "CPIAUCSL": 260.0, "GDPC1": 19000.0},
            {"date": "2022-01-01", "CPIAUCSL": 280.0, "GDPC1": 20000.0},
        ],
    }
    fake = FakeST()
    render_charts(fake, [chart])
    line_calls = [item for item in fake.calls if item[0] == "line_chart"]
    altair_calls = [item for item in fake.calls if item[0] == "altair_chart"]
    assert altair_calls or len(line_calls) >= 2
    for _name, args, kwargs in line_calls:
        y = kwargs.get("y")
        if isinstance(y, list):
            assert set(y) != {"CPIAUCSL", "GDPC1"}


def test_dual_axis_iso_dates_use_temporal_x() -> None:
    pytest.importorskip("altair")
    pytest.importorskip("pandas")
    from harness.charts import build_dual_axis_chart, render_charts

    chart = {
        "type": "line",
        "layout": "dual_axis",
        "shared_y_axis": False,
        "title": "CPI all items and Real GDP levels",
        "x_field": "date",
        "y_field": ["CPIAUCSL", "GDPC1"],
        "y_left": "CPIAUCSL",
        "y_right": "GDPC1",
        "y_left_label": "CPI all items",
        "y_right_label": "Real GDP",
        "data": [
            {"date": "2021-01-01", "CPIAUCSL": 260.0, "GDPC1": 19000.0},
            {"date": "2022-01-01", "CPIAUCSL": 280.0, "GDPC1": 20000.0},
            {"date": "2023-04-01", "CPIAUCSL": 300.0, "GDPC1": 21000.0},
        ],
    }

    layered = build_dual_axis_chart(chart, chart["data"], "date", ["CPIAUCSL", "GDPC1"])
    assert layered is not None
    spec = layered.to_dict()
    x_encodings = [
        layer["encoding"]["x"]
        for layer in spec.get("layer", [])
        if isinstance(layer, dict) and "encoding" in layer
    ]
    assert x_encodings
    assert all(item.get("type") == "temporal" for item in x_encodings)

    class FakeST:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def markdown(self, *args, **kwargs) -> None:
            self.calls.append(("markdown", args, kwargs))

        def caption(self, *args, **kwargs) -> None:
            self.calls.append(("caption", args, kwargs))

        def line_chart(self, *args, **kwargs) -> None:
            self.calls.append(("line_chart", args, kwargs))

        def altair_chart(self, spec, **kwargs) -> None:
            self.calls.append(("altair_chart", (spec,), kwargs))
            spec.to_dict()

        def expander(self, *args, **kwargs):
            from contextlib import contextmanager

            @contextmanager
            def _cm():
                yield self

            return _cm()

        def json(self, *args, **kwargs) -> None:
            self.calls.append(("json", args, kwargs))

        def info(self, *args, **kwargs) -> None:
            self.calls.append(("info", args, kwargs))

    fake = FakeST()
    render_charts(fake, [chart])
    altair_calls = [item for item in fake.calls if item[0] == "altair_chart"]
    assert altair_calls
    rendered = altair_calls[0][1][0].to_dict()
    rendered_x = [
        layer["encoding"]["x"]
        for layer in rendered.get("layer", [])
        if isinstance(layer, dict) and "encoding" in layer
    ]
    assert rendered_x
    assert all(item.get("type") == "temporal" for item in rendered_x)


def _cpi_and_gdp_data() -> DataArtifact:
    cpi_rows = []
    gdp_rows = []
    value = 260.0
    gdp_value = 19000.0
    for year in range(2021, 2027):
        for month in range(1, 13):
            if year == 2026 and month > 4:
                break
            cpi_rows.append(
                {
                    "series_id": "CPIAUCSL",
                    "date": f"{year}-{month:02d}-01",
                    "value": round(value, 3),
                }
            )
            value += 0.8
            if month in {1, 4, 7, 10}:
                gdp_rows.append(
                    {
                        "series_id": "GDPC1",
                        "date": f"{year}-{month:02d}-01",
                        "value": round(gdp_value, 3),
                    }
                )
                gdp_value += 80.0
    return DataArtifact(
        series_ids=["CPIAUCSL", "GDPC1"],
        observations={"CPIAUCSL": cpi_rows, "GDPC1": gdp_rows},
        metadata={"source": "FRED"},
    )
