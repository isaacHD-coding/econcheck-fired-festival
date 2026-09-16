from harness.charts import (
    apply_chart_brief,
    normalize_analysis_charts,
    normalize_chart,
    render_charts,
    would_dwarf_a_series,
    y_fields,
)
from harness.checkpoints.code import (
    ChartBriefCheckpoint,
    ChartHonestyCheckpoint,
    ChartLabelCheckpoint,
)
from harness.tools.code_runner import run_analysis_code
from workers.analysis_templates import relationship_analysis_code
from workers.artifacts import AnalysisArtifact, ChartBriefArtifact, CodeArtifact, DataArtifact, PlannerArtifact
from workers.chart_briefs import build_chart_brief, repair_chart_brief


ISAAC_QUESTION = (
    "What is the correlation (or anti correlation) between inflation and real GDP growth?"
)


def _relationship_plan() -> PlannerArtifact:
    return PlannerArtifact(
        question_type="relationship",
        economic_concepts=["inflation", "real GDP growth", "correlation"],
        measurement_strategy="Correlate CPIAUCSL and GDPC1 growth rates.",
        information_requirements=["CPIAUCSL", "GDPC1"],
        search_queries=["CPIAUCSL", "Real GDP GDPC1"],
        required_outputs=["correlation"],
        success_criteria=["Report the inflation/GDP correlation"],
    )


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
        metadata={"source": "FRED", "selected_series": [
            {"series_id": "CPIAUCSL", "units": "Index 1982-1984=100"},
            {"series_id": "GDPC1", "units": "Billions of Chained 2017 Dollars"},
        ]},
    )


def test_build_chart_brief_for_correlation_uses_growth_overlay() -> None:
    brief = build_chart_brief(_relationship_plan(), _cpi_and_gdp_data(), question=ISAAC_QUESTION)

    assert set(brief.series_ids) == {"CPIAUCSL", "GDPC1"}
    assert "growth" in brief.transforms
    assert brief.layout == "single"
    assert brief.chart_type == "line"
    assert brief.y_starts_at_zero is False
    assert "percent" in brief.units.lower()
    assert "CPI growth" in brief.title
    assert "Real GDP growth" in brief.title
    assert "align" in brief.notes.lower()
    assert "Do not place incompatible" not in brief.notes
    assert "Do not place incompatible" in brief.design_notes


def test_build_chart_brief_does_not_invent_unfetched_series() -> None:
    data = DataArtifact(
        series_ids=["CPIAUCSL"],
        observations={"CPIAUCSL": []},
        metadata={"source": "FRED"},
    )
    brief = build_chart_brief(_relationship_plan(), data, question=ISAAC_QUESTION)
    assert "GDPC1" not in brief.series_ids
    assert brief.series_ids == ["CPIAUCSL"]


def test_repair_chart_brief_drops_invented_series() -> None:
    data = _cpi_and_gdp_data()
    repaired = repair_chart_brief(
        ChartBriefArtifact(
            claim="Comovement using an invented series.",
            series_ids=["CPIAUCSL", "FAKEID"],
            transforms=["growth"],
            layout="single",
            y_starts_at_zero=False,
            time_window_rationale="Overlap.",
            annotations=[],
            title="Bad brief",
            x_label="date",
            y_label="percent",
            units="percent",
            notes="Invented FAKEID.",
            chart_type="line",
        ),
        _relationship_plan(),
        data,
        question=ISAAC_QUESTION,
    )
    assert "FAKEID" not in repaired.series_ids
    assert set(repaired.series_ids) <= {"CPIAUCSL", "GDPC1"}


def test_relationship_codegen_follows_brief_and_passes_guardrails() -> None:
    data = _cpi_and_gdp_data()
    brief = build_chart_brief(_relationship_plan(), data, question=ISAAC_QUESTION)
    data.metadata["chart_brief"] = brief.to_dict()
    analysis = run_analysis_code(CodeArtifact(code=relationship_analysis_code()), data)

    assert ChartBriefCheckpoint().evaluate(brief, data, question=ISAAC_QUESTION).passed is True
    assert ChartHonestyCheckpoint().evaluate(analysis).passed is True
    labeled = normalize_analysis_charts(analysis, brief)
    assert ChartLabelCheckpoint().evaluate(labeled).passed is True
    primary = labeled.charts[0]
    assert would_dwarf_a_series(primary) is False
    assert primary.get("unit") or primary.get("y_label")
    assert primary.get("series_id") or primary.get("series_ids")
    assert any("growth" in field for field in y_fields(primary)) or primary.get("layout") == "dual_axis"
    for chart in labeled.charts:
        notes = str(chart.get("notes") or "")
        assert "Do not place incompatible raw levels" not in notes
        assert not notes.lower().startswith("do not ")


def test_relationship_draft_explains_series_in_plain_english() -> None:
    from workers.analysis_templates import relationship_draft

    analysis = AnalysisArtifact(
        tables=[],
        metrics=[
            {
                "name": "growth_correlation",
                "value": -0.4625,
                "unit": "correlation",
                "source_series": ["CPIAUCSL", "GDPC1"],
            },
            {
                "name": "overlap_periods",
                "value": 18,
                "unit": "periods",
                "source_series": ["CPIAUCSL", "GDPC1"],
            },
        ],
        claims=[],
        charts=[{"type": "line", "notes": "Percent change after aligning mixed frequencies."}],
        method_notes="test",
        warnings=[],
    )
    draft = relationship_draft(analysis)
    text = draft.answer.lower()
    assert text.startswith("over this window")
    assert "inflation" in text
    assert "real gdp" in text
    assert "cpi all items" in text
    assert "cpiaucsl" in text
    assert "gdpc1" in text
    assert "contemporaneous association" not in text
    assert "moved opposite" in text
    ids_only = "cpiaucsl" in text and "gdpc1" in text and "cpi all" not in text and "real gdp" not in text
    assert ids_only is False


def test_chart_honesty_prefers_retry_over_releasing_dwarf_chart() -> None:
    analysis = AnalysisArtifact(
        tables=[],
        metrics=[
            {
                "name": "growth_correlation",
                "value": -0.4,
                "unit": "correlation",
                "source_series": ["CPIAUCSL", "GDPC1"],
            }
        ],
        claims=[],
        charts=[
            {
                "type": "line",
                "layout": "single",
                "title": "CPI vs GDP",
                "y_field": ["CPIAUCSL", "GDPC1"],
                "data": [
                    {"date": "2021-01-01", "CPIAUCSL": 270.0, "GDPC1": 22000.0},
                    {"date": "2022-01-01", "CPIAUCSL": 290.0, "GDPC1": 23000.0},
                ],
            }
        ],
        method_notes="misleading overlay",
        warnings=[],
    )
    result = ChartHonestyCheckpoint().evaluate(analysis)
    assert result.passed is False
    assert result.alarm is not None
    assert result.alarm.retry_from == "code_generation"
    rewritten = normalize_chart(analysis.charts[0])
    assert rewritten["layout"] == "dual_axis"
    assert would_dwarf_a_series(rewritten) is False


def test_apply_chart_brief_fills_units_and_series_ids() -> None:
    brief = build_chart_brief(_relationship_plan(), _cpi_and_gdp_data(), question=ISAAC_QUESTION)
    chart = apply_chart_brief(
        {"type": "line", "y_field": ["CPIAUCSL_growth", "GDPC1_growth"], "data": []},
        brief,
    )
    assert chart["unit"] == brief.units
    assert "CPIAUCSL" in str(chart.get("series_id") or chart.get("series_ids"))


def test_render_honors_stacked_brief_layout() -> None:
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
        "layout": "stacked",
        "title": "CPIAUCSL and GDPC1 levels",
        "x_field": "date",
        "y_field": ["CPIAUCSL", "GDPC1"],
        "unit": "mixed native units",
        "series_ids": ["CPIAUCSL", "GDPC1"],
        "data": [
            {"date": "2021-01-01", "CPIAUCSL": 260.0, "GDPC1": 19000.0},
            {"date": "2022-01-01", "CPIAUCSL": 280.0, "GDPC1": 20000.0},
        ],
    }
    fake = FakeST()
    render_charts(fake, [chart])
    line_calls = [item for item in fake.calls if item[0] == "line_chart"]
    assert len(line_calls) >= 2
    plotted = {call[2].get("y") for call in line_calls}
    assert "CPI all items" in plotted
    assert "Real GDP" in plotted
    assert "CPIAUCSL" not in plotted
    assert "GDPC1" not in plotted


def test_render_hides_instruction_notes_and_uses_human_legend() -> None:
    from harness.charts import public_chart_notes, render_charts

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
        "layout": "single",
        "title": "CPI growth vs Real GDP growth",
        "x_field": "date",
        "y_field": ["CPIAUCSL_growth", "GDPC1_growth"],
        "unit": "percent",
        "series_ids": ["CPIAUCSL", "GDPC1"],
        "notes": (
            "Align mixed frequencies with last-observation-carried-forward onto the "
            "lower-frequency dates. Do not place incompatible raw levels on one shared "
            "y-axis; if a levels companion is shown, use dual-axis or stacked panels."
        ),
        "data": [
            {"date": "2021-04-01", "CPIAUCSL_growth": 1.2, "GDPC1_growth": 0.4},
            {"date": "2021-07-01", "CPIAUCSL_growth": 0.8, "GDPC1_growth": -0.2},
        ],
    }
    assert "Do not place incompatible raw levels" not in public_chart_notes(chart)
    fake = FakeST()
    render_charts(fake, [chart])
    captions = " ".join(str(call[1][0]) for call in fake.calls if call[0] == "caption")
    assert "Do not place incompatible raw levels" not in captions
    line_calls = [item for item in fake.calls if item[0] == "line_chart"]
    assert line_calls
    y = line_calls[0][2].get("y")
    assert y == ["CPI growth", "Real GDP growth"]
