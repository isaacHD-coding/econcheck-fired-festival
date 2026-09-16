"""Shared question-classification helpers for checkpoints and workers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import re
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

DEFAULT_REQUESTED_WINDOW_YEARS = 5
YOY_RAW_HISTORY_BONUS_YEARS = 2
MAX_RAW_HISTORY_YEARS = 20

_NUMERIC_WINDOW_RE = re.compile(
    r"(?:last|past|over|previous|prior)\s+(?:the\s+)?(\d+)\s*(?:year|yr)s?",
    re.IGNORECASE,
)
_WORD_WINDOW_RE = re.compile(
    r"(?:last|past|over|previous|prior)\s+(?:the\s+)?"
    r"(one|two|three|four|five|six|seven|eight|nine|ten)\s+years?",
    re.IGNORECASE,
)
_WORD_YEARS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_YOY_TERMS = (
    "yoy",
    "year-over-year",
    "year over year",
    "year over-year",
    "12-month",
    "12 month",
)


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


def requested_window_years(question: str, plan: Any = None) -> int:
    """Parse N from 'last N years' in the question or plan. Default 5."""

    blob = f"{question} {_plan_text(plan)}"
    match = _NUMERIC_WINDOW_RE.search(blob)
    if match:
        return max(1, min(int(match.group(1)), MAX_RAW_HISTORY_YEARS))
    match = _WORD_WINDOW_RE.search(blob)
    if match:
        return _WORD_YEARS[match.group(1).lower()]
    return DEFAULT_REQUESTED_WINDOW_YEARS


def needs_yoy_raw_history(question: str, plan: Any = None) -> bool:
    """True when N years of inflation rates / YoY need more than N years of levels."""

    if is_comparison_question(question):
        return True
    blob = f" {normalize_question(question)} {_plan_text(plan)} "
    return any(term in blob for term in _YOY_TERMS)


def raw_history_years(question: str, plan: Any = None, extra_years: int = 0) -> int:
    """Raw FRED lookback in years. YoY of N years fetches N+2 (plus retry extras)."""

    requested = requested_window_years(question, plan)
    years = requested
    if needs_yoy_raw_history(question, plan):
        years = requested + YOY_RAW_HISTORY_BONUS_YEARS
    years += max(0, int(extra_years))
    return max(1, min(years, MAX_RAW_HISTORY_YEARS))


def years_ago(years: int, today: date | None = None) -> date:
    today = today or date.today()
    try:
        return today.replace(year=today.year - int(years))
    except ValueError:
        return today.replace(month=2, day=28, year=today.year - int(years))


def observation_start_for_fetch(
    question: str,
    plan: Any = None,
    *,
    today: date | None = None,
    extra_years: int = 0,
) -> date:
    """Earliest FRED observation_start for this question/plan."""

    return years_ago(
        raw_history_years(question, plan, extra_years=extra_years),
        today,
    )


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
