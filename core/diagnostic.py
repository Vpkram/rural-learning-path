"""Diagnostic sessions: resume, evaluate answers, and persist BKT mastery."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import sqlite3
from typing import Iterator
import uuid

from core.adaptive_engine import select_next_question
from core.mastery import BKTParameters, mastery_status, update_mastery


@dataclass(frozen=True)
class AnswerResult:
    question_id: int
    is_correct: bool
    student_answer: str
    student_answer_text: str
    correct_answer: str
    correct_answer_text: str
    explanation_en: str
    explanation_te: str
    topic_id: int
    mastery_score: float
    mastery_status: str
    answered_count: int
    question_limit: int
    session_status: str
    next_question: dict[str, object] | None
    study_plan_id: int | None = None


@dataclass(frozen=True)
class DiagnosticTopicResult:
    topic_id: int
    topic_key: str
    topic_name: str
    questions_asked: int
    correct_count: int
    percentage: float
    label: str


@dataclass(frozen=True)
class DiagnosticReviewItem:
    question_id: int
    topic_name: str
    prompt: str
    student_answer: str
    student_answer_text: str
    correct_answer: str
    correct_answer_text: str
    explanation_en: str
    explanation_te: str
    is_correct: bool


@dataclass(frozen=True)
class DiagnosticResults:
    session_key: str
    student_id: int
    subject_id: int
    total_questions: int
    correct_count: int
    percentage: float
    topics: tuple[DiagnosticTopicResult, ...]
    review: tuple[DiagnosticReviewItem, ...]


def topic_label_for_percentage(percentage: float) -> str:
    """Map a diagnostic percentage to its learner-facing topic label."""
    if not math.isfinite(percentage) or not 0 <= percentage <= 100:
        raise ValueError("percentage must be a finite value from 0 to 100.")
    if percentage < 50:
        return "Weak"
    if percentage < 80:
        return "Medium"
    return "Strong"


@contextmanager
def _savepoint(connection: sqlite3.Connection) -> Iterator[None]:
    """Keep answer, attempt, and mastery changes atomic, including in outer transactions."""
    name = f"diagnostic_{uuid.uuid4().hex}"
    connection.execute(f"SAVEPOINT {name}")
    try:
        yield
    except BaseException:
        connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
        connection.execute(f"RELEASE SAVEPOINT {name}")
        raise
    else:
        connection.execute(f"RELEASE SAVEPOINT {name}")


def start_diagnostic(
    connection: sqlite3.Connection,
    student_id: int,
    subject_id: int,
    question_limit: int = 15,
) -> dict[str, object]:
    """Create a new diagnostic session after validating available questions."""
    if (
        isinstance(student_id, bool)
        or not isinstance(student_id, int)
        or isinstance(subject_id, bool)
        or not isinstance(subject_id, int)
        or student_id <= 0
        or subject_id <= 0
    ):
        raise ValueError("A valid student and subject are required.")
    if isinstance(question_limit, bool) or not isinstance(question_limit, int) or question_limit <= 0:
        raise ValueError("question_limit must be greater than zero.")

    student = connection.execute("SELECT id FROM students WHERE id = ?", (student_id,)).fetchone()
    subject = connection.execute(
        "SELECT id FROM subjects WHERE id = ?", (subject_id,)
    ).fetchone()
    if student is None:
        raise ValueError("Student was not found.")
    if subject is None:
        raise ValueError("Subject was not found.")

    topic_counts = connection.execute(
        """
        SELECT t.id, t.topic_key, t.name, COUNT(q.id) AS question_count
        FROM topics AS t
        LEFT JOIN questions AS q
            ON q.topic_id = t.id AND q.subject_id = t.subject_id AND q.active = 1
        WHERE t.subject_id = ?
        GROUP BY t.id
        ORDER BY t.sequence_number, t.id
        """,
        (subject_id,),
    ).fetchall()
    if not topic_counts:
        raise ValueError("This subject has no topics with active questions yet.")
    underfilled_topics = [
        row["name"] for row in topic_counts if row["question_count"] < 2
    ]
    if underfilled_topics:
        raise ValueError(
            "Every topic needs at least two active diagnostic questions; "
            f"the question bank is incomplete for: {', '.join(underfilled_topics)}."
        )
    available = sum(row["question_count"] for row in topic_counts)
    if available == 0:
        raise ValueError("This subject has no active questions yet.")
    if question_limit > available:
        raise ValueError(f"Requested {question_limit} questions, but only {available} are available.")
    effective_limit = max(question_limit, 2 * len(topic_counts))
    if effective_limit > available:
        raise ValueError(
            "The selected subject does not have enough active questions to cover every topic twice."
        )

    session_key = uuid.uuid4().hex
    connection.execute(
        """
        INSERT INTO diagnostic_sessions (
            session_key, student_id, subject_id,
            requested_question_limit, question_limit
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_key, student_id, subject_id, question_limit, effective_limit),
    )
    connection.commit()
    first_question = select_next_question(connection, session_key)
    return {
        "session_key": session_key,
        "student_id": student_id,
        "subject_id": subject_id,
        "requested_question_limit": question_limit,
        "question_limit": effective_limit,
        "question_limit_adjusted": effective_limit != question_limit,
        "status": "active",
        "answered_count": 0,
        "current_question": first_question,
    }


def get_diagnostic_results(
    connection: sqlite3.Connection,
    session_key: str,
    student_id: int,
) -> DiagnosticResults:
    """Load a completed diagnostic's persisted topic scores and answer review."""
    session = connection.execute(
        """
        SELECT subject_id, status FROM diagnostic_sessions
        WHERE session_key = ? AND student_id = ?
        """,
        (session_key, student_id),
    ).fetchone()
    if session is None:
        raise ValueError("Diagnostic session was not found for this student.")
    if session["status"] != "completed":
        raise ValueError("Diagnostic results are available after the test is completed.")

    topics = connection.execute(
        """
        SELECT t.id AS topic_id, t.topic_key, t.name AS topic_name,
               dtr.questions_asked, dtr.correct_count, dtr.percentage, dtr.label
        FROM diagnostic_topic_results AS dtr
        JOIN topics AS t ON t.id = dtr.topic_id
        WHERE dtr.session_id = ? AND dtr.student_id = ? AND dtr.subject_id = ?
        ORDER BY t.sequence_number, t.id
        """,
        (session_key, student_id, session["subject_id"]),
    ).fetchall()
    if not topics:
        raise ValueError("No saved topic results were found for this diagnostic.")

    review_rows = connection.execute(
        """
        SELECT q.id AS question_id, t.name AS topic_name, q.prompt, a.answer,
               q.options_json, q.correct_answer, q.explanation_en, q.explanation_te,
               a.is_correct
        FROM attempts AS a
        JOIN questions AS q ON q.id = a.question_id
        JOIN topics AS t ON t.id = q.topic_id
        WHERE a.session_id = ? AND a.student_id = ? AND a.attempt_type = 'diagnostic'
          AND q.subject_id = ?
        ORDER BY a.answered_at, a.id
        """,
        (session_key, student_id, session["subject_id"]),
    ).fetchall()
    review = tuple(
        DiagnosticReviewItem(
            question_id=row["question_id"],
            topic_name=row["topic_name"],
            prompt=row["prompt"],
            student_answer=row["answer"],
            student_answer_text=json.loads(row["options_json"])[row["answer"]],
            correct_answer=row["correct_answer"],
            correct_answer_text=json.loads(row["options_json"])[row["correct_answer"]],
            explanation_en=row["explanation_en"],
            explanation_te=row["explanation_te"],
            is_correct=bool(row["is_correct"]),
        )
        for row in review_rows
    )
    total_questions = len(review)
    correct_count = sum(item.is_correct for item in review)
    return DiagnosticResults(
        session_key=session_key,
        student_id=student_id,
        subject_id=session["subject_id"],
        total_questions=total_questions,
        correct_count=correct_count,
        percentage=(100.0 * correct_count / total_questions) if total_questions else 0.0,
        topics=tuple(
            DiagnosticTopicResult(
                topic_id=row["topic_id"],
                topic_key=row["topic_key"],
                topic_name=row["topic_name"],
                questions_asked=row["questions_asked"],
                correct_count=row["correct_count"],
                percentage=row["percentage"],
                label=row["label"],
            )
            for row in topics
        ),
        review=review,
    )


def get_latest_diagnostic_result(
    connection: sqlite3.Connection,
    student_id: int,
    subject_id: int,
) -> DiagnosticResults | None:
    """Return this student's latest completed result for exactly one subject."""
    row = connection.execute(
        """
        SELECT ds.session_key
        FROM diagnostic_sessions AS ds
        WHERE ds.student_id = ? AND ds.subject_id = ? AND ds.status = 'completed'
          AND EXISTS (
              SELECT 1 FROM diagnostic_topic_results AS dtr
              WHERE dtr.session_id = ds.session_key
          )
        ORDER BY ds.completed_at DESC,
                 (
                     SELECT MAX(a.id)
                     FROM attempts AS a
                     WHERE a.session_id = ds.session_key
                       AND a.attempt_type = 'diagnostic'
                 ) DESC,
                 ds.created_at DESC
        LIMIT 1
        """,
        (student_id, subject_id),
    ).fetchone()
    if row is None:
        return None
    return get_diagnostic_results(connection, row["session_key"], student_id)


def get_diagnostic(
    connection: sqlite3.Connection,
    session_key: str,
    student_id: int,
) -> dict[str, object]:
    """Load a learner's diagnostic state and current unanswered question."""
    session = connection.execute(
        """
        SELECT session_key, student_id, subject_id, requested_question_limit,
               question_limit, status, created_at, updated_at
        FROM diagnostic_sessions
        WHERE session_key = ? AND student_id = ?
        """,
        (session_key, student_id),
    ).fetchone()
    if session is None:
        raise ValueError("Diagnostic session was not found for this student.")
    answered_count = connection.execute(
        "SELECT COUNT(*) FROM attempts WHERE session_id = ? AND attempt_type = 'diagnostic'",
        (session_key,),
    ).fetchone()[0]
    return {
        "session_key": session["session_key"],
        "student_id": session["student_id"],
        "subject_id": session["subject_id"],
        "requested_question_limit": session["requested_question_limit"],
        "question_limit": session["question_limit"],
        "question_limit_adjusted": (
            session["question_limit"] > session["requested_question_limit"]
        ),
        "status": session["status"],
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
        "answered_count": answered_count,
        "current_question": select_next_question(connection, session_key),
    }


def pause_diagnostic(
    connection: sqlite3.Connection,
    session_key: str,
    student_id: int,
) -> None:
    """Pause an active session so it can be resumed later."""
    cursor = connection.execute(
        """
        UPDATE diagnostic_sessions
        SET status = 'paused', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE session_key = ? AND student_id = ? AND status = 'active'
        """,
        (session_key, student_id),
    )
    if cursor.rowcount != 1:
        raise ValueError("Only this student's active diagnostic can be paused.")
    connection.commit()


def resume_diagnostic(
    connection: sqlite3.Connection,
    session_key: str,
    student_id: int,
) -> dict[str, object]:
    """Resume a paused diagnostic, returning the next unanswered question."""
    cursor = connection.execute(
        """
        UPDATE diagnostic_sessions
        SET status = 'active', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE session_key = ? AND student_id = ? AND status = 'paused'
        """,
        (session_key, student_id),
    )
    if cursor.rowcount != 1:
        raise ValueError("Only this student's paused diagnostic can be resumed.")
    connection.commit()
    return get_diagnostic(connection, session_key, student_id)


def submit_answer(
    connection: sqlite3.Connection,
    session_key: str,
    student_id: int,
    question_id: int,
    answer: str,
    response_time_seconds: float,
    parameters: BKTParameters = BKTParameters(),
) -> AnswerResult:
    """Check an answer, atomically record it, and update topic mastery."""
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("Choose one of the available answer options.")
    try:
        response_time = float(response_time_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("Response time must be a non-negative number.") from exc
    if not math.isfinite(response_time) or response_time < 0:
        raise ValueError("Response time must be a finite, non-negative number.")

    with _savepoint(connection):
        session = connection.execute(
            """
            SELECT subject_id, question_limit, status
            FROM diagnostic_sessions
            WHERE session_key = ? AND student_id = ?
            """,
            (session_key, student_id),
        ).fetchone()
        if session is None:
            raise ValueError("Diagnostic session was not found for this student.")
        if session["status"] != "active":
            raise ValueError("This diagnostic session is not active.")

        question = connection.execute(
            """
            SELECT id, topic_id, difficulty, options_json, correct_answer,
                   explanation_en, explanation_te
            FROM questions
            WHERE id = ? AND subject_id = ? AND active = 1
            """,
            (question_id, session["subject_id"]),
        ).fetchone()
        if question is None:
            raise ValueError("Question is not available in this diagnostic subject.")

        options = json.loads(question["options_json"])
        chosen_answer = answer.strip()
        matching_key = next(
            (key for key in options if key.casefold() == chosen_answer.casefold()),
            None,
        )
        if matching_key is None:
            raise ValueError("Answer must match one of the available option keys.")

        repeated = connection.execute(
            """
            SELECT 1 FROM attempts
            WHERE session_id = ? AND question_id = ? AND attempt_type = 'diagnostic'
            """,
            (session_key, question_id),
        ).fetchone()
        if repeated is not None:
            raise ValueError("This question has already been answered in this session.")

        expected_question = select_next_question(connection, session_key)
        if expected_question is None:
            raise ValueError("There is no unanswered question available in this session.")
        if expected_question["id"] != question_id:
            raise ValueError("Submit the current diagnostic question before moving on.")

        answered_count = connection.execute(
            "SELECT COUNT(*) FROM attempts WHERE session_id = ? AND attempt_type = 'diagnostic'",
            (session_key,),
        ).fetchone()[0]
        if answered_count >= session["question_limit"]:
            raise ValueError("This diagnostic has already reached its question limit.")

        is_correct = matching_key == question["correct_answer"]
        current_mastery = connection.execute(
            "SELECT score FROM mastery WHERE student_id = ? AND topic_id = ?",
            (student_id, question["topic_id"]),
        ).fetchone()
        previous_score = current_mastery["score"] if current_mastery else 0.30
        new_score = update_mastery(previous_score, is_correct, parameters)
        new_status = mastery_status(new_score)

        connection.execute(
            """
            INSERT INTO attempts (
                student_id, question_id, session_id, attempt_type, answer,
                is_correct, response_time_seconds, presented_difficulty
            )
            VALUES (?, ?, ?, 'diagnostic', ?, ?, ?, ?)
            """,
            (
                student_id,
                question_id,
                session_key,
                matching_key,
                int(is_correct),
                response_time,
                question["difficulty"],
            ),
        )
        connection.execute(
            """
            INSERT INTO mastery (student_id, topic_id, score, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(student_id, topic_id) DO UPDATE SET
                score = excluded.score,
                status = excluded.status,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """,
            (student_id, question["topic_id"], new_score, new_status),
        )

        answered_count += 1
        completed = answered_count >= session["question_limit"]
        new_session_status = "completed" if completed else "active"
        connection.execute(
            """
            UPDATE diagnostic_sessions
            SET status = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                completed_at = CASE
                    WHEN ? = 'completed' THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    ELSE completed_at
                END
            WHERE session_key = ?
            """,
            (new_session_status, new_session_status, session_key),
        )
        if completed:
            topic_results = connection.execute(
                """
                SELECT t.id AS topic_id, COUNT(a.id) AS questions_asked,
                       COALESCE(SUM(a.is_correct), 0) AS correct_count
                FROM topics AS t
                LEFT JOIN questions AS q
                    ON q.topic_id = t.id AND q.subject_id = t.subject_id
                LEFT JOIN attempts AS a
                    ON a.question_id = q.id
                    AND a.session_id = ?
                    AND a.student_id = ?
                    AND a.attempt_type = 'diagnostic'
                WHERE t.subject_id = ?
                GROUP BY t.id
                ORDER BY t.sequence_number, t.id
                """,
                (session_key, student_id, session["subject_id"]),
            ).fetchall()
            connection.executemany(
                """
                INSERT INTO diagnostic_topic_results (
                    session_id, student_id, subject_id, topic_id,
                    questions_asked, correct_count, percentage, label
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        session_key,
                        student_id,
                        session["subject_id"],
                        row["topic_id"],
                        row["questions_asked"],
                        row["correct_count"],
                        (
                            100.0 * row["correct_count"] / row["questions_asked"]
                            if row["questions_asked"]
                            else 0.0
                        ),
                        topic_label_for_percentage(
                            (
                                100.0 * row["correct_count"] / row["questions_asked"]
                                if row["questions_asked"]
                                else 0.0
                            )
                        ),
                    )
                    for row in topic_results
                ],
            )
        next_question = (
            None if completed else select_next_question(connection, session_key)
        )

    connection.commit()
    study_plan_id: int | None = None
    if completed:
        from core.planner import build_study_plan

        study_plan = build_study_plan(connection, student_id, session["subject_id"])
        study_plan_id = study_plan.plan_id
    return AnswerResult(
        question_id=question["id"],
        is_correct=is_correct,
        student_answer=matching_key,
        student_answer_text=options[matching_key],
        correct_answer=question["correct_answer"],
        correct_answer_text=options[question["correct_answer"]],
        explanation_en=question["explanation_en"],
        explanation_te=question["explanation_te"],
        topic_id=question["topic_id"],
        mastery_score=new_score,
        mastery_status=new_status,
        answered_count=answered_count,
        question_limit=session["question_limit"],
        session_status=new_session_status,
        next_question=next_question,
        study_plan_id=study_plan_id,
    )
