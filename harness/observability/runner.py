"""Integration seam between the Streamlit UI and the harness runner."""

SAMPLE_RUN_ID = "sample_cpi_run"


def run_question(question: str) -> str:
    """Return the fixture run for any submitted question.

    This keeps the chat page harness-aware without depending on the live
    orchestrator. A later branch can replace this body with orchestrator.run(...).
    """

    if not question.strip():
        return SAMPLE_RUN_ID
    return SAMPLE_RUN_ID
