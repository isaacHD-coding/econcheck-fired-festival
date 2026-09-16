from harness.domain import (
    is_canonical_cpi_demo_question,
    is_comparison_question,
    is_cpi_question,
    is_relationship_question,
    plan_requests_relationship,
    wanted_series_for_question,
)
from workers.artifacts import PlannerArtifact


ISAAC_QUESTION = (
    "What is the correlation (or anti correlation) between inflation and real GDP growth?"
)


def test_canonical_cpi_demo_question_is_exact() -> None:
    assert is_canonical_cpi_demo_question(
        "What has happened to CPI inflation over the last five years?"
    )
    assert is_canonical_cpi_demo_question(
        "what has happened to cpi inflation over the last five years"
    )
    assert not is_canonical_cpi_demo_question(ISAAC_QUESTION)


def test_relationship_question_is_not_classified_as_cpi_only() -> None:
    assert is_relationship_question(ISAAC_QUESTION)
    assert not is_cpi_question(ISAAC_QUESTION)
    assert is_cpi_question("What has happened to CPI inflation over the last five years?")


CPI_PCE_QUESTION = (
    "What is the difference between CPI and PCE inflation over the last 5 years?"
)


def test_cpi_pce_difference_is_a_comparison_not_cpi_only() -> None:
    assert is_comparison_question(CPI_PCE_QUESTION)
    assert not is_cpi_question(CPI_PCE_QUESTION)
    assert not is_relationship_question(CPI_PCE_QUESTION)
    assert wanted_series_for_question(CPI_PCE_QUESTION) == ["CPIAUCSL", "PCEPI"]


def test_plan_requests_relationship_detects_gdp_and_inflation() -> None:
    plan = PlannerArtifact(
        question_type="relationship",
        economic_concepts=["inflation", "real GDP"],
        measurement_strategy="Correlate CPIAUCSL and GDPC1 growth.",
        information_requirements=["CPI", "real GDP"],
        search_queries=["CPIAUCSL", "GDPC1"],
        required_outputs=["correlation"],
        success_criteria=["Report the correlation"],
    )

    assert plan_requests_relationship(plan) is True
