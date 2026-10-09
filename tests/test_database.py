import json
import sqlite3

import pytest

from db.database import get_connection, initialize_database
from db.seed import load_question_bank, seed_database


def make_seeded_connection(tmp_path):
    connection = get_connection(tmp_path / "test.db")
    initialize_database(connection)
    seed_database(connection, load_question_bank())
    return connection


def test_schema_and_seed_load_catalog(tmp_path):
    with make_seeded_connection(tmp_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM subjects").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == 5
        assert connection.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 40
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_seed_is_safe_to_run_twice(tmp_path):
    with make_seeded_connection(tmp_path) as connection:
        seed_database(connection, load_question_bank())
        assert connection.execute("SELECT COUNT(*) FROM subjects").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 40


def test_question_rows_have_translated_explanations_and_valid_options(tmp_path):
    with make_seeded_connection(tmp_path) as connection:
        rows = connection.execute(
            "SELECT options_json, correct_answer, explanation_en, explanation_te FROM questions"
        ).fetchall()
        for row in rows:
            options = json.loads(row["options_json"])
            assert row["correct_answer"] in options
            assert row["explanation_en"].strip()
            assert row["explanation_te"].strip()


def test_question_bank_has_eight_questions_per_topic_across_all_difficulties():
    bank = load_question_bank()
    for topic in bank["topics"]:
        questions = [question for question in bank["questions"] if question["topic_key"] == topic["key"]]
        assert len(questions) == 8
        assert {question["difficulty"] for question in questions} == {1, 2, 3, 4, 5}


def test_load_question_bank_reports_invalid_json(tmp_path):
    bad_bank = tmp_path / "broken.json"
    bad_bank.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="Could not read question bank"):
        load_question_bank(bad_bank)


def test_schema_rejects_invalid_difficulty(tmp_path):
    with make_seeded_connection(tmp_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO questions (
                    question_key, subject_id, topic_id, difficulty, prompt,
                    options_json, correct_answer, explanation_en, explanation_te
                ) VALUES ('bad', 1, 1, 6, 'Question?', '{}', 'A', 'en', 'te')
                """
            )


def test_schema_supports_resumable_diagnostic_sessions(tmp_path):
    with make_seeded_connection(tmp_path) as connection:
        connection.execute(
            """
            INSERT INTO students (username, password_hash, display_name, class_level)
            VALUES ('learner', 'test-hash', 'Learner', 'College')
            """
        )
        connection.execute(
            """
            INSERT INTO diagnostic_sessions (session_key, student_id, subject_id, question_limit)
            VALUES ('session-1', 1, 1, 15)
            """
        )
        connection.execute(
            "UPDATE diagnostic_sessions SET status = 'paused' WHERE session_key = ?",
            ("session-1",),
        )
        session = connection.execute(
            "SELECT question_limit, status FROM diagnostic_sessions WHERE session_key = ?",
            ("session-1",),
        ).fetchone()
        assert session["question_limit"] == 15
        assert session["status"] == "paused"


def test_initialize_database_migrates_existing_diagnostic_sessions(tmp_path):
    connection = get_connection(tmp_path / "legacy.db")
    connection.executescript(
        """
        CREATE TABLE students (id INTEGER PRIMARY KEY);
        CREATE TABLE subjects (id INTEGER PRIMARY KEY);
        CREATE TABLE diagnostic_sessions (
            session_key TEXT PRIMARY KEY,
            student_id INTEGER NOT NULL REFERENCES students(id),
            subject_id INTEGER NOT NULL REFERENCES subjects(id),
            question_limit INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            completed_at TEXT
        );
        """
    )
    connection.commit()

    initialize_database(connection)

    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(diagnostic_sessions)")
    }
    assert "requested_question_limit" in columns

    connection.execute("INSERT INTO students (id) VALUES (1)")
    connection.execute("INSERT INTO subjects (id) VALUES (1)")
    connection.execute(
        """
        INSERT INTO topics (id, subject_id, topic_key, name)
        VALUES (1, 1, 'legacy-topic', 'Legacy Topic')
        """
    )
    connection.execute(
        """
        INSERT INTO questions (
            id, question_key, subject_id, topic_id, difficulty, prompt,
            options_json, correct_answer, explanation_en, explanation_te
        )
        VALUES (1, 'legacy-question', 1, 1, 1, 'Question?', '{"A":"Yes","B":"No"}',
                'A', 'Explanation', 'వివరణ')
        """
    )
    connection.execute(
        """
        INSERT INTO diagnostic_sessions (
            session_key, student_id, subject_id, question_limit, status, completed_at
        )
        VALUES ('legacy-complete', 1, 1, 1, 'completed', '2026-01-01T00:00:00Z')
        """
    )
    connection.execute(
        """
        INSERT INTO attempts (
            student_id, question_id, session_id, attempt_type, answer,
            is_correct, response_time_seconds, presented_difficulty
        )
        VALUES (1, 1, 'legacy-complete', 'diagnostic', 'A', 1, 2, 1)
        """
    )
    connection.commit()
    initialize_database(connection)

    result = connection.execute(
        """
        SELECT questions_asked, correct_count, percentage, label
        FROM diagnostic_topic_results
        WHERE session_id = 'legacy-complete' AND topic_id = 1
        """
    ).fetchone()
    assert tuple(result) == (1, 1, 100.0, "Strong")
