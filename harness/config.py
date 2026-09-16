"""Environment and secret resolution for EconCheck.

API keys are resolved from, in order:

1. An explicit function argument (for example a Streamlit password field)
2. Process environment variables
3. A local ``.env`` file
4. Streamlit secrets, when the app is running under Streamlit

Keys are never written to run artifacts.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any


FRED_API_KEY_ENV = "FRED_API_KEY"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"


@lru_cache(maxsize=1)
def load_env_files() -> None:
    """Load a local ``.env`` file if python-dotenv is installed."""

    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(override=False)


def resolve_fred_api_key(explicit: str | None = None) -> str | None:
    """Return a FRED API key without logging or persisting it."""

    load_env_files()
    return _first_nonempty(
        explicit,
        os.environ.get(FRED_API_KEY_ENV),
        _streamlit_secret(FRED_API_KEY_ENV),
    )


def resolve_openai_api_key(explicit: str | None = None) -> str | None:
    """Return an OpenAI API key without logging or persisting it."""

    load_env_files()
    return _first_nonempty(
        explicit,
        os.environ.get(OPENAI_API_KEY_ENV),
        _streamlit_secret(OPENAI_API_KEY_ENV),
    )


def _first_nonempty(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        cleaned = str(value).strip()
        if cleaned:
            return cleaned
    return None


def _streamlit_secret(name: str) -> str | None:
    try:
        import streamlit as st
    except Exception:
        return None

    try:
        secrets = st.secrets
        value = secrets.get(name)
    except Exception:
        return None

    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
