from app.chat_state import (
    CANONICAL_QUESTION,
    CURRENT_RUN_ID_KEY,
    MOCK_MODE,
    OPENAI_MODE,
    QUESTION_KEY,
    RUN_IN_PROGRESS_KEY,
    WORKER_MODE_KEY,
    init_chat_state,
    mark_run_finished,
    mark_run_started,
    reconcile_interrupted_run,
)


def test_chat_state_survives_observability_round_trip() -> None:
    session: dict = {}
    init_chat_state(session)
    session[QUESTION_KEY] = (
        "What is the correlation (or anti correlation) between inflation "
        "and real GDP growth?"
    )
    session[WORKER_MODE_KEY] = OPENAI_MODE
    mark_run_started(session, "run-isaac")

    # Observability reads current_run_id but must not clear chat keys.
    viewed = session.get(CURRENT_RUN_ID_KEY)
    init_chat_state(session)

    assert viewed == "run-isaac"
    assert session[CURRENT_RUN_ID_KEY] == "run-isaac"
    assert session[RUN_IN_PROGRESS_KEY] is True
    assert "correlation" in session[QUESTION_KEY]
    assert session[WORKER_MODE_KEY] == OPENAI_MODE
    assert session[QUESTION_KEY] != CANONICAL_QUESTION


def test_interrupted_in_progress_run_is_detected_on_chat_remount() -> None:
    session: dict = {}
    init_chat_state(session)
    mark_run_started(session, "run-partial")

    interrupted = reconcile_interrupted_run(session, current_stage="planning")

    assert interrupted is True
    assert session[CURRENT_RUN_ID_KEY] == "run-partial"
    assert session["run_in_progress"] is False


def test_finished_run_is_not_treated_as_interrupted() -> None:
    session: dict = {}
    init_chat_state(session)
    mark_run_started(session, "run-done")
    mark_run_finished(session)

    assert reconcile_interrupted_run(session, current_stage="released") is False
    assert session[CURRENT_RUN_ID_KEY] == "run-done"


def test_init_chat_state_does_not_reset_existing_run() -> None:
    session = {
        CURRENT_RUN_ID_KEY: "run-keep",
        QUESTION_KEY: "custom question",
        WORKER_MODE_KEY: OPENAI_MODE,
        "run_in_progress": True,
    }

    init_chat_state(session, default_question=CANONICAL_QUESTION, default_mode=MOCK_MODE)

    assert session[CURRENT_RUN_ID_KEY] == "run-keep"
    assert session[QUESTION_KEY] == "custom question"
    assert session[WORKER_MODE_KEY] == OPENAI_MODE
