import sqlite3

import pytest

from core.auth import (
    AuthenticationError,
    authenticate_student,
    register_student,
)
from db.database import get_connection, initialize_database


def make_connection(tmp_path):
    connection = get_connection(tmp_path / "auth.db")
    initialize_database(connection)
    return connection


def test_registration_hashes_password_and_login_returns_safe_profile(tmp_path):
    connection = make_connection(tmp_path)
    student_id = register_student(
        connection,
        username="  learner_one ",
        password="secure pass 123",
        display_name="A Student",
        class_level="Class 9",
        preferred_language="te",
    )
    row = connection.execute(
        "SELECT password_hash FROM students WHERE id = ?",
        (student_id,),
    ).fetchone()
    assert row["password_hash"] != "secure pass 123"
    assert row["password_hash"].startswith("$2")
    assert authenticate_student(
        connection,
        username="LEARNER_ONE",
        password="secure pass 123",
    ) == {
        "id": student_id,
        "username": "learner_one",
        "display_name": "A Student",
        "class_level": "Class 9",
        "preferred_language": "te",
    }


def test_login_rejects_unknown_user_and_wrong_password(tmp_path):
    connection = make_connection(tmp_path)
    register_student(
        connection,
        username="student",
        password="secure pass 123",
        display_name="Student",
        class_level="Class 8",
    )
    with pytest.raises(AuthenticationError, match="incorrect"):
        authenticate_student(connection, username="missing", password="secure pass 123")
    with pytest.raises(AuthenticationError, match="incorrect"):
        authenticate_student(connection, username="student", password="incorrect pass")


def test_registration_rejects_duplicate_username_and_invalid_password(tmp_path):
    connection = make_connection(tmp_path)
    register_student(
        connection,
        username="student",
        password="secure pass 123",
        display_name="Student",
        class_level="College",
    )
    with pytest.raises(AuthenticationError, match="already registered"):
        register_student(
            connection,
            username="STUDENT",
            password="secure pass 123",
            display_name="Duplicate",
            class_level="College",
        )
    with pytest.raises(AuthenticationError, match="at least 8"):
        register_student(
            connection,
            username="student2",
            password="short",
            display_name="Student",
            class_level="College",
        )
    with pytest.raises(AuthenticationError, match="72"):
        register_student(
            connection,
            username="student3",
            password="x" * 73,
            display_name="Student",
            class_level="College",
        )


def test_corrupted_bcrypt_hash_is_a_friendly_auth_error(tmp_path):
    connection = make_connection(tmp_path)
    connection.execute(
        """
        INSERT INTO students (username, password_hash, display_name, class_level)
        VALUES ('bad_hash', 'not-a-bcrypt-hash', 'Bad Hash', 'College')
        """
    )
    connection.commit()
    with pytest.raises(AuthenticationError, match="password record is invalid"):
        authenticate_student(connection, username="bad_hash", password="secure pass 123")
