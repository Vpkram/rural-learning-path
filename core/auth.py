"""Local student registration and authentication with bcrypt password hashes."""

from __future__ import annotations

import re
import sqlite3

import bcrypt

_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
_MIN_PASSWORD_BYTES = 8
_MAX_PASSWORD_BYTES = 72


class AuthenticationError(ValueError):
    """A friendly, expected account validation or sign-in failure."""


def _validate_username(username: str) -> str:
    if not isinstance(username, str):
        raise AuthenticationError("Username must be text.")
    normalized = username.strip()
    if not _USERNAME_PATTERN.fullmatch(normalized):
        raise AuthenticationError(
            "Username must be 3-32 characters using letters, numbers, dot, dash, or underscore."
        )
    return normalized


def _validate_password(password: str) -> bytes:
    if not isinstance(password, str):
        raise AuthenticationError("Password must be text.")
    encoded = password.encode("utf-8")
    if len(encoded) < _MIN_PASSWORD_BYTES:
        raise AuthenticationError("Password must contain at least 8 UTF-8 bytes.")
    if len(encoded) > _MAX_PASSWORD_BYTES:
        raise AuthenticationError("Password is too long for bcrypt (maximum 72 UTF-8 bytes).")
    return encoded


def register_student(
    connection: sqlite3.Connection,
    *,
    username: str,
    password: str,
    display_name: str,
    class_level: str,
    preferred_language: str = "en",
) -> int:
    """Create a student account and return its database ID."""
    normalized_username = _validate_username(username)
    password_bytes = _validate_password(password)
    normalized_name = display_name.strip() if isinstance(display_name, str) else ""
    normalized_class = class_level.strip() if isinstance(class_level, str) else ""
    if not normalized_name or len(normalized_name) > 80:
        raise AuthenticationError("Enter a display name of at most 80 characters.")
    if not normalized_class or len(normalized_class) > 40:
        raise AuthenticationError("Enter a class or program name of at most 40 characters.")
    if preferred_language not in {"en", "te"}:
        raise AuthenticationError("Choose English or Telugu as your language.")

    password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("ascii")
    try:
        cursor = connection.execute(
            """
            INSERT INTO students (
                username, password_hash, display_name, class_level, preferred_language
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                normalized_username,
                password_hash,
                normalized_name,
                normalized_class,
                preferred_language,
            ),
        )
        connection.commit()
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise AuthenticationError("That username is already registered.") from exc
    return int(cursor.lastrowid)


def authenticate_student(
    connection: sqlite3.Connection,
    *,
    username: str,
    password: str,
) -> dict[str, object]:
    """Verify credentials and return only safe student profile fields."""
    normalized_username = _validate_username(username)
    password_bytes = _validate_password(password)
    row = connection.execute(
        """
        SELECT id, username, password_hash, display_name, class_level, preferred_language
        FROM students
        WHERE username = ? COLLATE NOCASE
        """,
        (normalized_username,),
    ).fetchone()
    if row is None:
        raise AuthenticationError("Username or password is incorrect.")
    try:
        password_matches = bcrypt.checkpw(password_bytes, row["password_hash"].encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise AuthenticationError("This account's password record is invalid.") from exc
    if not password_matches:
        raise AuthenticationError("Username or password is incorrect.")
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "class_level": row["class_level"],
        "preferred_language": row["preferred_language"],
    }
