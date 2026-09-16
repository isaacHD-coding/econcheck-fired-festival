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


def normalize_question(question: str) -> str:
    return " ".join(str(question).lower().split()).strip(" ?!.")


def is_canonical_cpi_demo_question(question: str) -> bool:
    return normalize_question(question) == normalize_question(CANONICAL_CPI_QUESTION)


def is_relationship_question(question: str) -> bool:
    text = f" {normalize_question(question)} "
    if any(term in text for term in _RELATIONSHIP_TERMS):
        return True
    mentions_inflation = "inflation" in text or " cpi " in text or text.startswith("cpi ")
    mentions_gdp = "gdp" in text or "gross domestic" in text
    return mentions_inflation and mentions_gdp


def is_cpi_question(question: str) -> bool:
    """True for CPI-trend questions, not for multi-series relationship questions."""

    if is_relationship_question(question):
        return False
    text = normalize_question(question)
    return "cpi" in text or "consumer price" in text or "inflation" in text


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
