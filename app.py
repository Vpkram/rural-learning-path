"""Streamlit entry point for the student learning application."""

from __future__ import annotations

import sqlite3

import streamlit as st

from core.logging_config import configure_app_logging
from db.database import DEFAULT_DATABASE_PATH, get_connection, initialize_database
from db.seed import seed_all_subjects
from llm.ollama_client import OllamaClient
from ui.components import render_header, show_friendly_error
from ui.student_view import render_authentication, render_student_page
from ui.styles import apply_styles

DEFAULT_SETTINGS = {
    "temperature": 0.2,
    "top_k": 3,
    "similarity_threshold": 0.35,
    "chunk_size": 900,
    "chunk_overlap": 120,
}


def main() -> None:
    logger = configure_app_logging()
    st.set_page_config(
        page_title="Rural Learning Path",
        page_icon="📘",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_styles()
    if "language" not in st.session_state:
        st.session_state["language"] = "en"

    language_column, title_column = st.columns([1, 4])
    current_student = st.session_state.get("student")
    language_widget_key = (
        f"language_selector_{current_student['id']}"
        if current_student is not None
        else "language_selector_guest"
    )
    if language_widget_key not in st.session_state:
        st.session_state[language_widget_key] = (
            current_student["preferred_language"]
            if current_student is not None
            else st.session_state["language"]
        )
    with language_column:
        st.selectbox(
            "Language / భాష",
            ["en", "te"],
            format_func=lambda value: "English" if value == "en" else "తెలుగు",
            key=language_widget_key,
        )
    st.session_state["language"] = st.session_state[language_widget_key]
    st.session_state.setdefault("app_settings", DEFAULT_SETTINGS.copy())

    connection: sqlite3.Connection | None = None
    try:
        connection = get_connection(DEFAULT_DATABASE_PATH)
        initialize_database(connection)
        if not st.session_state.get("subject_catalog_seeded"):
            seed_all_subjects(connection)
            st.session_state["subject_catalog_seeded"] = True
        client = OllamaClient(timeout=1.5)
        with title_column:
            models, _active_model = render_header(st.session_state["language"], client)
        student = st.session_state.get("student")
        if student is None:
            st.subheader("Your personal learning space" if st.session_state["language"] == "en" else "మీ వ్యక్తిగత అభ్యాస స్థలం")
            render_authentication(connection)
            return
        connection.execute(
            "UPDATE students SET preferred_language = ? WHERE id = ?",
            (st.session_state["language"], student["id"]),
        )
        connection.commit()

        page, subject = _render_sidebar(connection, student)
        render_student_page(connection, student, subject, page, models)
    except (sqlite3.Error, OSError, ValueError) as exc:
        logger.exception("Application could not load local data")
        show_friendly_error(
            "The learning app could not load its local data.",
            f"{exc}\n\nCheck that the project data folder is writable, then restart the app.",
        )
    except Exception:
        # Keep a local UI failure from exposing a traceback or crashing the page.
        logger.exception("Unhandled error while rendering the application")
        show_friendly_error(
            "Something went wrong while showing this page.",
            "Try refreshing the page. If the issue continues, ask your project mentor to review the local logs.",
        )
    finally:
        if connection is not None:
            connection.close()


def _render_sidebar(
    connection: sqlite3.Connection,
    student: dict[str, object],
):
    # Imported lazily to keep app startup focused and avoid duplicate auth setup.
    from ui.student_view import _sidebar_navigation

    return _sidebar_navigation(connection, student)


if __name__ == "__main__":
    main()
