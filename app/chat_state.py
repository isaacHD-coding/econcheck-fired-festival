"""Session helpers so chat progress survives Observability navigation."""

from __future__ import annotations

from typing import Any, MutableMapping


QUESTION_KEY = "question_text"
WORKER_MODE_KEY = "worker_mode"
CURRENT_RUN_ID_KEY = "current_run_id"
RUN_IN_PROGRESS_KEY = "run_in_progress"

CANONICAL_QUESTION = "What has happened to CPI inflation over the last five years?"
MOCK_MODE = "Mock demo"
OPENAI_MODE = "OpenAI agent"


def init_chat_state(
    session_state: MutableMapping[str, Any],
    *,
    default_question: str = CANONICAL_QUESTION,
    default_mode: str = MOCK_MODE,
) -> MutableMapping[str, Any]:
    """Initialize chat keys without wiping an existing in-progress run."""

    session_state.setdefault(QUESTION_KEY, default_question)
    session_state.setdefault(WORKER_MODE_KEY, default_mode)
    session_state.setdefault(CURRENT_RUN_ID_KEY, None)
    session_state.setdefault(RUN_IN_PROGRESS_KEY, False)
    return session_state


def mark_run_started(session_state: MutableMapping[str, Any], run_id: str) -> None:
    session_state[CURRENT_RUN_ID_KEY] = run_id
    session_state[RUN_IN_PROGRESS_KEY] = True


def mark_run_finished(session_state: MutableMapping[str, Any]) -> None:
    session_state[RUN_IN_PROGRESS_KEY] = False


def reconcile_interrupted_run(
    session_state: MutableMapping[str, Any],
    *,
    current_stage: str | None,
) -> bool:
    """Clear the in-progress flag if the script remounted mid-run.

    Returns True when a previously live run was interrupted by navigation.
    """

    if not session_state.get(RUN_IN_PROGRESS_KEY):
        return False
    if current_stage in {"released", "escalated"}:
        session_state[RUN_IN_PROGRESS_KEY] = False
        return False
    session_state[RUN_IN_PROGRESS_KEY] = False
    return True
