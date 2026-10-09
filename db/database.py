"""Small SQLite helpers shared by the app and seed script."""

from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "learning_path.db"
SCHEMA_PATH = Path(__file__).resolve().with_name("schema.sql")


def get_connection(database_path: str | Path = DEFAULT_DATABASE_PATH) -> sqlite3.Connection:
    """Open a row-friendly SQLite connection with foreign keys enabled."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    """Create any missing application tables from the checked-in schema."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    connection.executescript(schema)
    session_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(diagnostic_sessions)")
    }
    if "requested_question_limit" not in session_columns:
        connection.execute(
            """
            ALTER TABLE diagnostic_sessions
            ADD COLUMN requested_question_limit INTEGER NOT NULL DEFAULT 15
            """
        )
        connection.execute(
            """
            UPDATE diagnostic_sessions
            SET requested_question_limit = question_limit
            """
        )
    subject_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(subjects)")
    }
    if "stream" not in subject_columns:
        connection.execute("ALTER TABLE subjects ADD COLUMN stream TEXT NOT NULL DEFAULT ''")
    if "content_status" not in subject_columns:
        connection.execute(
            "ALTER TABLE subjects ADD COLUMN content_status TEXT NOT NULL DEFAULT 'complete'"
        )
    connection.execute(
        """
        INSERT OR IGNORE INTO diagnostic_topic_results (
            session_id, student_id, subject_id, topic_id,
            questions_asked, correct_count, percentage, label
        )
        SELECT
            ds.session_key,
            ds.student_id,
            ds.subject_id,
            t.id,
            COUNT(a.id),
            COALESCE(SUM(a.is_correct), 0),
            CASE WHEN COUNT(a.id) = 0 THEN 0.0
                 ELSE 100.0 * SUM(a.is_correct) / COUNT(a.id)
            END,
            CASE
                WHEN COUNT(a.id) = 0 OR 100.0 * SUM(a.is_correct) / COUNT(a.id) < 50
                    THEN 'Weak'
                WHEN 100.0 * SUM(a.is_correct) / COUNT(a.id) < 80
                    THEN 'Medium'
                ELSE 'Strong'
            END
        FROM diagnostic_sessions AS ds
        JOIN topics AS t ON t.subject_id = ds.subject_id
        LEFT JOIN questions AS q ON q.topic_id = t.id AND q.subject_id = ds.subject_id
        LEFT JOIN attempts AS a
            ON a.question_id = q.id
            AND a.session_id = ds.session_key
            AND a.student_id = ds.student_id
            AND a.attempt_type = 'diagnostic'
        WHERE ds.status = 'completed'
        GROUP BY ds.session_key, ds.student_id, ds.subject_id, t.id
        """
    )
    connection.commit()
