"""Streamlit observability page for the EconCheck harness."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from app.observability import main
except ImportError:
    from observability import main


if __name__ == "__main__":
    main()
