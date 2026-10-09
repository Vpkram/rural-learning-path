"""Select the next unseen question based on topic coverage and mastery."""

from __future__ import annotations

import json
import sqlite3

DEFAULT_PRIOR_MASTERY = 0.30


def _difficulty_for_mastery(score: float) -> int:
    """Use gentler questions for lower mastery and harder ones for higher mastery."""
    if score < 0.30:
        return 1
    if score < 0.50:
        return 2
    if score < 0.70:
        return 3
    if score < 0.85:
        return 4
    return 5


def select_next_question(
    connection: sqlite3.Connection,
    session_key: str,
) -> dict[str, object] | None:
    """Return the best unseen question, without exposing its answer.

    Topics with fewer answers are sampled first so a diagnostic starts with a
    balanced picture. Once coverage is balanced, lower mastery takes priority.
    """
    session = connection.execute(
        """
        SELECT student_id, subject_id, question_limit, status
        FROM diagnostic_sessions
        WHERE session_key = ?
        """,
        (session_key,),
    ).fetchone()
    if session is None:
        raise ValueError("Diagnostic session was not found.")
    if session["status"] != "active":
        return None

    answered_count = connection.execute(
        "SELECT COUNT(*) FROM attempts WHERE session_id = ? AND attempt_type = 'diagnostic'",
        (session_key,),
    ).fetchone()[0]
    if answered_count >= session["question_limit"]:
        return None

    candidates = connection.execute(
        """
        SELECT
            q.id AS question_id,
            q.question_key,
            q.topic_id,
            q.difficulty,
            q.prompt,
            q.options_json,
            t.topic_key,
            t.name AS topic_name,
            t.sequence_number,
            COALESCE(m.score, ?) AS mastery_score,
            (
                SELECT COUNT(*)
                FROM attempts AS a
                JOIN questions AS answered ON answered.id = a.question_id
                WHERE a.session_id = ?
                  AND a.attempt_type = 'diagnostic'
                  AND answered.topic_id = q.topic_id
            ) AS topic_attempt_count
        FROM questions AS q
        JOIN topics AS t ON t.id = q.topic_id
        LEFT JOIN mastery AS m
            ON m.topic_id = q.topic_id AND m.student_id = ?
        WHERE q.subject_id = ?
          AND q.active = 1
          AND NOT EXISTS (
              SELECT 1 FROM attempts AS previous
              WHERE previous.session_id = ?
                AND previous.question_id = q.id
                AND previous.attempt_type = 'diagnostic'
          )
        """,
        (
            DEFAULT_PRIOR_MASTERY,
            session_key,
            session["student_id"],
            session["subject_id"],
            session_key,
        ),
    ).fetchall()
    if not candidates:
        raise ValueError("No unseen active questions remain in this diagnostic.")

    question = min(
        candidates,
        key=lambda row: (
            row["topic_attempt_count"],
            row["mastery_score"],
            row["sequence_number"],
            abs(row["difficulty"] - _difficulty_for_mastery(row["mastery_score"])),
            row["question_id"],
        ),
    )
    return {
        "id": question["question_id"],
        "key": question["question_key"],
        "topic_id": question["topic_id"],
        "topic_key": question["topic_key"],
        "topic_name": question["topic_name"],
        "difficulty": question["difficulty"],
        "prompt": question["prompt"],
        "options": json.loads(question["options_json"]),
    }
