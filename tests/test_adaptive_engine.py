import pytest

from core.adaptive_engine import select_next_question
from core.diagnostic import (
    get_diagnostic,
    pause_diagnostic,
    resume_diagnostic,
    start_diagnostic,
    submit_answer,
)
from core.mastery import BKTParameters, mastery_status, update_mastery
from core.weak_topics import detect_weak_topics
from db.database import get_connection, initialize_database
from db.seed import load_question_bank, seed_database


def seeded_database(tmp_path):
    connection = get_connection(tmp_path / "adaptive.db")
    initialize_database(connection)
    seed_database(connection, load_question_bank())
    connection.execute(
        """
        INSERT INTO students (username, password_hash, display_name, class_level)
        VALUES ('test-learner', 'not-a-real-password-hash', 'Test Learner', 'College')
        """
    )
    connection.commit()
    subject_id = connection.execute("SELECT id FROM subjects WHERE subject_key = 'dbms'").fetchone()[0]
    return connection, subject_id


def test_bkt_correct_answer_increases_mastery_and_wrong_answer_accounts_for_slip():
    prior = 0.30
    after_correct = update_mastery(prior, True)
    after_wrong = update_mastery(prior, False)
    assert after_correct > prior
    assert 0 < after_wrong < prior
    assert mastery_status(0.39) == "Weak"
    assert mastery_status(0.40) == "Developing"
    assert mastery_status(0.80) == "Strong"


def test_bkt_rejects_invalid_probability_settings_and_scores():
    with pytest.raises(ValueError):
        BKTParameters(guess=1.0)
    with pytest.raises(ValueError):
        update_mastery(float("nan"), True)


def test_diagnostic_starts_balanced_and_does_not_repeat_questions(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    session = start_diagnostic(connection, 1, subject_id, question_limit=3)
    first = session["current_question"]
    assert first is not None

    submitted = submit_answer(
        connection,
        session["session_key"],
        1,
        first["id"],
        next(iter(first["options"])),
        12.0,
    )
    second = submitted.next_question
    assert second is not None
    assert second["id"] != first["id"]
    assert second["topic_id"] != first["topic_id"]


def test_diagnostic_updates_mastery_and_completes_at_limit(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    session = start_diagnostic(connection, 1, subject_id, question_limit=1)
    assert session["question_limit"] == 10
    assert session["question_limit_adjusted"]
    question = session["current_question"]
    result = None
    while question is not None:
        correct_answer = connection.execute(
            "SELECT correct_answer FROM questions WHERE id = ?",
            (question["id"],),
        ).fetchone()["correct_answer"]
        result = submit_answer(
            connection,
            session["session_key"],
            1,
            question["id"],
            correct_answer,
            3,
        )
        question = result.next_question
    assert result is not None
    assert result.answered_count == session["question_limit"]
    assert result.session_status == "completed"
    assert result.next_question is None
    assert result.study_plan_id is not None
    assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 10
    assert connection.execute("SELECT COUNT(*) FROM mastery").fetchone()[0] == 5
    assert connection.execute(
        "SELECT COUNT(*) FROM study_plans WHERE id = ?", (result.study_plan_id,)
    ).fetchone()[0] == 1


def test_pause_and_resume_returns_unanswered_question(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    session = start_diagnostic(connection, 1, subject_id, question_limit=2)
    pause_diagnostic(connection, session["session_key"], 1)
    assert get_diagnostic(connection, session["session_key"], 1)["status"] == "paused"
    resumed = resume_diagnostic(connection, session["session_key"], 1)
    assert resumed["status"] == "active"
    assert resumed["current_question"] is not None


def test_submission_rejects_invalid_options_and_repeat(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    session = start_diagnostic(connection, 1, subject_id, question_limit=2)
    question = session["current_question"]
    with pytest.raises(ValueError, match="available option"):
        submit_answer(connection, session["session_key"], 1, question["id"], "not-an-option", 2)
    option = next(iter(question["options"]))
    submit_answer(connection, session["session_key"], 1, question["id"], option, 2)
    with pytest.raises(ValueError, match="already been answered"):
        submit_answer(connection, session["session_key"], 1, question["id"], option, 2)


def test_submission_rejects_a_question_that_was_not_current(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    session = start_diagnostic(connection, 1, subject_id, question_limit=2)
    current_question_id = session["current_question"]["id"]
    another_question_id = connection.execute(
        "SELECT id FROM questions WHERE id <> ? ORDER BY id LIMIT 1",
        (current_question_id,),
    ).fetchone()[0]
    with pytest.raises(ValueError, match="current diagnostic question"):
        submit_answer(
            connection,
            session["session_key"],
            1,
            another_question_id,
            "A",
            2,
        )
    assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0


def test_adaptive_selector_rejects_unknown_session(tmp_path):
    connection, _subject_id = seeded_database(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        select_next_question(connection, "missing")


def test_weak_topic_detection_and_prerequisite_root_cause(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    topic_ids = {
        row["topic_key"]: row["id"]
        for row in connection.execute("SELECT id, topic_key FROM topics")
    }
    connection.execute(
        "INSERT OR IGNORE INTO topic_prerequisites (topic_id, prerequisite_topic_id) VALUES (?, ?)",
        (topic_ids["normalization"], topic_ids["sql-basics"]),
    )
    connection.execute(
        """
        INSERT INTO mastery (student_id, topic_id, score, status)
        VALUES (1, ?, 0.2, 'Weak')
        """,
        (topic_ids["sql-basics"],),
    )
    question_id = connection.execute(
        "SELECT id FROM questions WHERE question_key = 'dbms-007'"
    ).fetchone()[0]
    for _ in range(3):
        connection.execute(
            """
            INSERT INTO attempts (
                student_id, question_id, session_id, attempt_type, answer,
                is_correct, response_time_seconds, presented_difficulty
            ) VALUES (1, ?, 'weak-test', 'practice', 'B', 0, 30, 1)
            """,
            (question_id,),
        )

    topics = detect_weak_topics(connection, 1, subject_id)
    by_key = {topic.topic_key: topic for topic in topics}
    assert by_key["sql-basics"].status == "Weak"
    assert "sql-basics" in by_key["normalization"].root_cause_topic_keys
    assert by_key["sql-basics"].accuracy == 0
