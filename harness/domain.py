"""Shared question-classification helpers for checkpoints and workers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


CANONICAL_CPI_QUESTION = (
    "What has happened to CPI inflation over the last five years?"
)

_RELATIONSHIP_TERMS = (
    "correlation",
    "anti-correlation",
    "anticorrelation",
    "anti correlation",
    "lead-lag",
    "lead lag",
    "relationship between",
    " vs ",
    " versus ",
    "compared with",
    "compared to",
    "co-movement",
    "comovement",
)

_COMPARISON_TERMS = (
    "difference between",
    "gap between",
    "differ between",
    "compared with",
    "compared to",
    " vs ",
    " versus ",
)

CPI_PCE_SERIES = ("CPIAUCSL", "PCEPI")
INFLATION_GDP_SERIES = ("CPIAUCSL", "GDPC1")


def normalize_question(question: str) -> str:
    return " ".join(str(question).lower().split()).strip(" ?!.")


def is_canonical_cpi_demo_question(question: str) -> bool:
    return normalize_question(question) == normalize_question(CANONICAL_CPI_QUESTION)


def is_relationship_question(question: str) -> bool:
    text = f" {normalize_question(question)} "
    if is_comparison_question(question) and not _mentions_gdp(text):
        return False
    if any(term in text for term in _RELATIONSHIP_TERMS):
        return True
    mentions_inflation = "inflation" in text or " cpi " in text or text.startswith("cpi ")
    return mentions_inflation and _mentions_gdp(text)


def is_comparison_question(question: str) -> bool:
    """True for two-inflation-index questions such as CPI vs PCE."""

    text = f" {normalize_question(question)} "
    mentions_cpi = "cpi" in text or "consumer price" in text
    mentions_pce = (
        " pce " in text
        or "pcepi" in text
        or "personal consumption" in text
    )
    if mentions_cpi and mentions_pce:
        return True
    if _mentions_gdp(text):
        return False
    return mentions_cpi and any(term in text for term in _COMPARISON_TERMS)


def is_multi_series_question(question: str) -> bool:
    return is_relationship_question(question) or is_comparison_question(question)


def wanted_series_for_question(question: str) -> list[str]:
    if is_comparison_question(question):
        return list(CPI_PCE_SERIES)
    if is_relationship_question(question):
        return list(INFLATION_GDP_SERIES)
    if is_cpi_question(question):
        return ["CPIAUCSL"]
    return []


def is_cpi_question(question: str) -> bool:
    """True for CPI-trend questions, not for multi-series comparison/relationship questions."""

    if is_multi_series_question(question):
        return False
    text = normalize_question(question)
    return "cpi" in text or "consumer price" in text or "inflation" in text


def _mentions_gdp(text: str) -> bool:
    return "gdp" in text or "gross domestic" in text


def plan_requests_relationship(plan: Any) -> bool:
    blob = _plan_text(plan)
    if any(term in blob for term in _RELATIONSHIP_TERMS):
        return True
    mentions_inflation = "inflation" in blob or "cpi" in blob or "cpiaucsl" in blob
    mentions_gdp = "gdp" in blob or "gdpc1" in blob or "gross domestic" in blob
    return mentions_inflation and mentions_gdp


def _plan_text(plan: Any) -> str:
    if plan is None:
        return ""
    if hasattr(plan, "to_dict"):
        plan = plan.to_dict()
    if isinstance(plan, Mapping):
        parts: list[str] = []
        for value in plan.values():
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, list):
                parts.extend(str(item) for item in value)
        return " ".join(parts).lower()
    return str(plan).lower()
