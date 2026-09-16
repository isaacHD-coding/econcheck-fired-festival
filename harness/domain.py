"""Shared question-classification helpers for checkpoints and workers."""

from __future__ import annotations


def is_cpi_question(question: str) -> bool:
    text = " ".join(str(question).lower().split())
    return "cpi" in text or "consumer price" in text or "inflation" in text
