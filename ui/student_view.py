"""Student-facing Streamlit pages for the learning-path prototype."""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
from pathlib import Path
import re

import streamlit as st

from core.auth import AuthenticationError, authenticate_student, register_student
from core.diagnostic import (
    DiagnosticResults,
    get_diagnostic,
    get_diagnostic_results,
    get_latest_diagnostic_result,
    pause_diagnostic,
    resume_diagnostic,
    start_diagnostic,
    submit_answer,
)
from core.llm_tutor import TutorGenerationError, tutor_response
from core.planner import (
    build_study_plan,
    get_active_study_plan,
    set_plan_task_completed,
)
from core.subject_videos import (
    search_videos_url,
    topic_video_entries,
    video_render_action,
)
from core.video_recommender import VideoDataError
from core.weak_topics import TopicInsight, detect_weak_topics
from db.database import PROJECT_ROOT
from db.seed import find_subject_pack_directory
from llm.model_selector import NoModelAvailableError
from llm.ollama_client import (
    OllamaClient,
    OllamaConnectionError,
    OllamaError,
)
from rag.embeddings import EmbeddingError, SentenceTransformerEmbeddings
from rag.indexer import IndexingCancelled, index_textbook, textbook_cache_key
from rag.loader import DocumentLoadError
from rag.models import RetrievalResult
from rag.retriever import NOT_FOUND_MESSAGE, retrieve
from ui.components import render_retrieved_chunks, show_friendly_error
from ui.styles import status_badge

TEXTBOOK_DIRECTORY = PROJECT_ROOT / "data" / "textbooks"
DATA_DIRECTORY = PROJECT_ROOT / "data"
DIAGNOSTIC_FIRST_MESSAGE = "Take the diagnostic test first so your plan matches your level"


def plan_number_label(plan) -> str:
    """Use the same persisted generation label on every student page."""
    return f"Plan {plan.generation}"


def plan_task_widget_key(plan, task) -> str:
    """Build stable task widget keys from the owning plan and task sequence."""
    return f"task_{plan.student_id}_{plan.subject_id}_{plan.plan_id}_{task.task_id}"


def diagnostic_plan_prompt(latest_result: DiagnosticResults | None) -> str | None:
    """Return the plan gate message only when this subject lacks test results."""
    return DIAGNOSTIC_FIRST_MESSAGE if latest_result is None else None


def _save_plan_task_checkbox(
    connection: sqlite3.Connection,
    student_id: int,
    task_id: int,
    widget_key: str,
) -> None:
    """Persist the checkbox's new state and surface any database error."""
    logger = logging.getLogger("learning_path")
    try:
        set_plan_task_completed(
            connection,
            student_id,
            task_id,
            bool(st.session_state[widget_key]),
        )
    except (ValueError, sqlite3.Error):
        logger.exception(
            "Could not save study-plan checkbox state for student %s and task %s",
            student_id,
            task_id,
        )
        show_friendly_error(
            "Could not save task progress.",
            "Your local database could not save that change. Please retry.",
        )


def tutor_default_question(subject_name: str, topic_name: str, mode: str) -> str:
    """Build a prompt that follows the selected subject and topic."""
    if mode == "hint":
        return f"Give me a hint about {topic_name} in {subject_name}."
    if mode == "practice":
        return f"Create practice questions about {topic_name} in {subject_name}."
    return f"Explain {topic_name} in {subject_name} using simple words."


def draft_content_label(subject: sqlite3.Row | dict[str, object]) -> str | None:
    """Return the review badge text only for a draft pack."""
    return "Draft content · under review" if subject["content_status"] == "draft" else None


def render_topic_video(
    topic: str,
    class_name: str,
    subject_name: str,
    stream: str,
    entry: dict[str, object] | None,
) -> None:
    """Render a verified playable video, otherwise a contextual search action."""
    st.markdown(f"**{topic}**")
    action, video_url = video_render_action(entry)
    if action == "search":
        st.link_button(
            f"Search videos for {topic}",
            search_videos_url(class_name, subject_name, topic, stream=stream),
        )
        return
    st.caption(
        f"{entry.get('title') or 'Verified video'} · "
        f"{entry.get('duration_min') or '?'} min · {entry.get('source') or 'Source'}"
    )
    st.video(video_url)


TEXT = {
    "en": {
        "login": "Sign in",
        "register": "Create account",
        "username": "Username",
        "password": "Password",
        "display_name": "Your name",
        "class_level": "Class / program",
        "language": "Language",
        "home": "My progress",
        "diagnostic": "Diagnostic test",
        "plan": "Study plan",
        "tutor": "Tutor",
        "settings": "Settings",
        "subject": "Subject",
        "class": "Class",
        "logout": "Sign out",
        "start_test": "Start diagnostic",
        "pause_test": "Pause and resume later",
        "submit": "Submit answer",
        "resume": "Resume",
        "new_test": "Start a new test",
        "no_subject": "No subject is available for this class yet.",
        "no_test": "Start a diagnostic to discover topics to work on.",
        "no_plan": "There is no active plan yet.",
        "rebuild_plan": "Build or refresh my plan",
        "diagnostic_first": "Take the diagnostic test first so your plan matches your level",
        "go_to_test": "Go to diagnostic test",
        "full_syllabus": "Build a full-syllabus plan anyway",
        "no_book": "No PDF or DOCX textbook is indexed yet.",
        "select_book": "Choose a textbook",
        "upload_book": "Or add a local textbook",
        "question": "Ask about this topic",
        "top_k": "Retrieved passages",
        "threshold": "Similarity threshold",
        "chunk_size": "Chunk size (characters)",
        "overlap": "Chunk overlap (characters)",
        "temperature": "Tutor creativity",
        "model": "Ollama model",
        "settings_saved": "Settings are saved for this browser session.",
        "active_model": "Active model",
        "connected": "Connected",
        "not_connected": "Not Connected",
    },
    "te": {
        "login": "లాగిన్",
        "register": "ఖాతా సృష్టించండి",
        "username": "వినియోగదారు పేరు",
        "password": "పాస్‌వర్డ్",
        "display_name": "మీ పేరు",
        "class_level": "తరగతి / కోర్సు",
        "language": "భాష",
        "home": "నా పురోగతి",
        "diagnostic": "స్థాయి పరీక్ష",
        "plan": "అభ్యాస ప్రణాళిక",
        "tutor": "బోధకుడు",
        "settings": "సెట్టింగులు",
        "subject": "విషయం",
        "class": "తరగతి",
        "logout": "లాగ్ అవుట్",
        "start_test": "స్థాయి పరీక్ష ప్రారంభించండి",
        "pause_test": "తర్వాత కొనసాగించడానికి ఆపండి",
        "submit": "సమాధానం సమర్పించండి",
        "resume": "కొనసాగించండి",
        "new_test": "కొత్త పరీక్ష ప్రారంభించండి",
        "no_subject": "ఈ తరగతికి ఇంకా విషయం అందుబాటులో లేదు.",
        "no_test": "మీకు అభ్యాసం అవసరమైన అంశాలను తెలుసుకోవడానికి పరీక్ష ప్రారంభించండి.",
        "no_plan": "ప్రస్తుతం క్రియాశీల ప్రణాళిక లేదు.",
        "rebuild_plan": "నా ప్రణాళికను రూపొందించండి లేదా నవీకరించండి",
        "diagnostic_first": "మీ స్థాయికి సరిపోయే ప్రణాళిక కోసం ముందుగా స్థాయి పరీక్ష రాయండి",
        "go_to_test": "స్థాయి పరీక్షకు వెళ్లండి",
        "full_syllabus": "అయినా పూర్తి పాఠ్యాంశ ప్రణాళిక రూపొందించండి",
        "no_book": "ఇంకా PDF లేదా DOCX పాఠ్యపుస్తకం సూచిక చేయలేదు.",
        "select_book": "పాఠ్యపుస్తకాన్ని ఎంచుకోండి",
        "upload_book": "లేదా స్థానిక పాఠ్యపుస్తకాన్ని జోడించండి",
        "question": "ఈ అంశం గురించి అడగండి",
        "top_k": "పొందిన భాగాలు",
        "threshold": "సామ్య పరిమితి",
        "chunk_size": "భాగం పరిమాణం (అక్షరాలు)",
        "overlap": "భాగాల అతివ్యాప్తి (అక్షరాలు)",
        "temperature": "బోధకుడి సృజనాత్మకత",
        "model": "Ollama మోడల్",
        "settings_saved": "ఈ బ్రౌజర్ సెషన్‌కు సెట్టింగులు సేవ్ అయ్యాయి.",
        "active_model": "క్రియాశీల మోడల్",
        "connected": "కనెక్ట్ అయింది",
        "not_connected": "కనెక్ట్ కాలేదు",
    },
}


def tx(language: str, key: str) -> str:
    return TEXT.get(language, TEXT["en"]).get(key, TEXT["en"].get(key, key))


def _friendly_exception(exc: Exception, language: str = "en") -> str:
    if isinstance(exc, OllamaConnectionError):
        return (
            "Ollama is not running. Start Ollama locally and try again."
            if language == "en"
            else "Ollama నడవడం లేదు. స్థానికంగా Ollama ప్రారంభించి మళ్లీ ప్రయత్నించండి."
        )
    if isinstance(exc, NoModelAvailableError):
        return str(exc)
    if isinstance(exc, EmbeddingError):
        return f"Textbook search is unavailable: {exc}"
    if isinstance(exc, (DocumentLoadError, VideoDataError, AuthenticationError, ValueError, OSError, OllamaError)):
        return str(exc)
    return "Something went wrong. Please retry or contact your teacher."


def render_authentication(connection: sqlite3.Connection) -> dict[str, object] | None:
    """Render login/registration and return the verified learner profile."""
    language = st.session_state.get("language", "en")
    login_tab, register_tab = st.tabs([tx(language, "login"), tx(language, "register")])
    with login_tab:
        with st.form("login_form"):
            username = st.text_input(tx(language, "username"))
            password = st.text_input(tx(language, "password"), type="password")
            submitted = st.form_submit_button(tx(language, "login"), use_container_width=True)
        if submitted:
            try:
                profile = authenticate_student(connection, username=username, password=password)
                st.session_state["student"] = profile
                st.session_state["language"] = profile["preferred_language"]
                st.rerun()
            except AuthenticationError as exc:
                st.error(str(exc))
    with register_tab:
        with st.form("register_form"):
            username = st.text_input(tx(language, "username"), key="register_username")
            display_name = st.text_input(tx(language, "display_name"))
            available_classes = ordered_class_levels(
                [
                    row["class_level"]
                    for row in connection.execute(
                        "SELECT DISTINCT class_level FROM subjects"
                    )
                ]
            )
            class_level = st.selectbox(
                tx(language, "class_level"),
                available_classes or ["College"],
            )
            password = st.text_input(tx(language, "password"), type="password", key="register_password")
            preferred_language = st.selectbox(
                tx(language, "language"),
                ["en", "te"],
                format_func=lambda value: "English" if value == "en" else "తెలుగు",
            )
            submitted = st.form_submit_button(tx(language, "register"), use_container_width=True)
        if submitted:
            try:
                student_id = register_student(
                    connection,
                    username=username,
                    password=password,
                    display_name=display_name,
                    class_level=class_level,
                    preferred_language=preferred_language,
                )
                profile = authenticate_student(
                    connection,
                    username=username,
                    password=password,
                )
                if profile["id"] != student_id:
                    raise AuthenticationError("Could not verify the new account.")
                st.session_state["student"] = profile
                st.session_state["language"] = preferred_language
                st.rerun()
            except (AuthenticationError, sqlite3.Error) as exc:
                st.error(_friendly_exception(exc, language))
    return None


def _subject_options(
    connection: sqlite3.Connection,
    class_level: str,
    stream: str | None = None,
) -> list[sqlite3.Row]:
    if stream is None:
        stream_condition = "AND stream = ''"
        parameters = (class_level,)
    else:
        stream_condition = "AND stream = ?"
        parameters = (class_level, stream)
    return connection.execute(
        f"""
        SELECT id, subject_key, name, class_level, stream, content_status
        FROM subjects
        WHERE class_level = ? {stream_condition}
        ORDER BY name
        """,
        parameters,
    ).fetchall()


def ordered_class_levels(class_levels: list[str]) -> list[str]:
    """Order standard classes numerically, followed by College."""
    selected = set(class_levels)
    school_classes = [f"Class {number}" for number in range(1, 13)]
    ordered = [name for name in school_classes if name in selected]
    if "College" in selected:
        ordered.append("College")
    ordered.extend(sorted(selected - set(school_classes) - {"College"}, key=str.casefold))
    return ordered


def select_subjects_for_class(
    connection: sqlite3.Connection,
    class_level: str,
    stream: str | None = None,
) -> list[sqlite3.Row]:
    """Return only subjects in a selected class and optional stream."""
    return _subject_options(connection, class_level, stream)


def _navigate_to_diagnostic(language: str) -> None:
    st.session_state["student_page"] = tx(language, "diagnostic")


def _sidebar_navigation(
    connection: sqlite3.Connection,
    student: dict[str, object],
) -> tuple[str, sqlite3.Row | None]:
    language = st.session_state.get("language", "en")
    st.sidebar.write(f"**{student['display_name']}**")
    class_options = connection.execute(
        "SELECT DISTINCT class_level FROM subjects ORDER BY class_level"
    ).fetchall()
    class_levels = ordered_class_levels([row["class_level"] for row in class_options])
    default_class = (
        student["class_level"]
        if student["class_level"] in class_levels
        else (class_levels[0] if class_levels else student["class_level"])
    )
    class_level = st.sidebar.selectbox(
        tx(language, "class"),
        class_levels or [default_class],
        index=(class_levels.index(default_class) if default_class in class_levels else 0),
        key="selected_class",
    )
    streams = [
        row["stream"]
        for row in connection.execute(
            """
            SELECT DISTINCT stream FROM subjects
            WHERE class_level = ? AND stream != ''
            ORDER BY stream
            """,
            (class_level,),
        )
    ]
    selected_stream = None
    if streams:
        selected_stream = st.sidebar.selectbox(
            "Stream",
            streams,
            key=f"selected_stream_{class_level}",
        )
    subjects = select_subjects_for_class(connection, class_level, selected_stream)
    subject = None
    if subjects:
        current_id = st.session_state.get("selected_subject_id")
        subject_ids = [row["id"] for row in subjects]
        subjects_by_id = {row["id"]: row for row in subjects}
        selected_index = subject_ids.index(current_id) if current_id in subject_ids else 0
        selected_id = st.sidebar.selectbox(
            tx(language, "subject"),
            subject_ids,
            index=selected_index,
            format_func=lambda row_id: subjects_by_id[row_id]["name"],
            key=f"subject_choice_{class_level}",
        )
        selected = subjects_by_id[selected_id]
        subject = selected
        st.session_state["selected_subject_id"] = selected["id"]
    else:
        st.sidebar.info(tx(language, "no_subject"))

    pages = [
        tx(language, "home"),
        tx(language, "diagnostic"),
        tx(language, "plan"),
        tx(language, "tutor"),
        tx(language, "settings"),
    ]
    if st.session_state.get("student_page") not in pages:
        st.session_state["student_page"] = pages[0]
    page = st.sidebar.radio(
        "Navigation" if language == "en" else "విభాగాలు",
        pages,
        key="student_page",
    )
    if st.sidebar.button(tx(language, "logout"), use_container_width=True):
        st.session_state.pop("student", None)
        st.rerun()
    return page, subject


def render_home(connection: sqlite3.Connection, student: dict[str, object], subject: sqlite3.Row | None) -> None:
    language = st.session_state.get("language", "en")
    st.header(tx(language, "home"))
    if subject is None:
        st.info(tx(language, "no_subject"))
        return
    insights = detect_weak_topics(connection, student["id"], subject["id"])
    if not insights:
        st.info("This subject has no topics yet.")
        return
    average_mastery = sum(topic.mastery_score for topic in insights) / len(insights)
    st.metric("Overall topic mastery", f"{average_mastery:.0%}")
    latest_result = get_latest_diagnostic_result(
        connection,
        student["id"],
        subject["id"],
    )
    if latest_result is not None:
        st.subheader("Latest diagnostic results")
        st.metric(
            "Diagnostic score",
            f"{latest_result.correct_count}/{latest_result.total_questions}",
            f"{latest_result.percentage:.0f}%",
        )
        st.table(
            [
                {
                    "Topic": topic.topic_name,
                    "Questions asked": topic.questions_asked,
                    "Correct": topic.correct_count,
                    "Percentage": f"{topic.percentage:.0f}%",
                    "Level": topic.label,
                }
                for topic in latest_result.topics
            ]
        )
    columns = st.columns(min(3, len(insights)))
    for index, insight in enumerate(insights):
        with columns[index % len(columns)]:
            st.subheader(insight.topic_name)
            tone = insight.status.casefold()
            st.markdown(status_badge(insight.status, tone), unsafe_allow_html=True)
            st.progress(min(1.0, max(0.0, insight.mastery_score)))
            if insight.root_cause_topic_keys:
                st.caption(f"Review prerequisites: {', '.join(insight.root_cause_topic_keys)}")
    active = get_active_study_plan(connection, student["id"], subject["id"])
    if active is not None:
        completed_count = sum(task.is_completed for task in active.tasks)
        st.caption(
            f"Active {plan_number_label(active)} · {completed_count}/{len(active.tasks)} "
            f"tasks complete"
        )


def _open_diagnostic_sessions(
    connection: sqlite3.Connection,
    student_id: int,
    subject_id: int,
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT session_key, status, question_limit, updated_at
        FROM diagnostic_sessions
        WHERE student_id = ? AND subject_id = ? AND status IN ('active', 'paused')
        ORDER BY updated_at DESC
        """,
        (student_id, subject_id),
    ).fetchall()


def _render_diagnostic_results(
    connection: sqlite3.Connection,
    student: dict[str, object],
    results: DiagnosticResults,
) -> None:
    st.subheader("Diagnostic results")
    st.metric(
        "Total score",
        f"{results.correct_count}/{results.total_questions}",
        f"{results.percentage:.0f}%",
    )
    st.subheader("Results by topic")
    st.table(
        [
            {
                "Topic": topic.topic_name,
                "Questions asked": topic.questions_asked,
                "Correct": topic.correct_count,
                "Percentage": f"{topic.percentage:.0f}%",
                "Level": topic.label,
            }
            for topic in results.topics
        ]
    )
    from ui.result_charts import render_diagnostic_charts

    render_diagnostic_charts(results.topics)
    st.subheader("Review every question")
    language = st.session_state.get("language", "en")
    for index, item in enumerate(results.review, start=1):
        answer = f"{item.student_answer}. {item.student_answer_text}"
        correct = f"{item.correct_answer}. {item.correct_answer_text}"
        with st.container():
            if item.is_correct:
                st.success(f"{index}. Correct · {item.topic_name}")
            else:
                st.error(f"{index}. Wrong · {item.topic_name}")
            st.write(item.prompt)
            st.write(f"Your answer: {answer}")
            st.write(f"Correct answer: {correct}")
            st.write(item.explanation_te if language == "te" else item.explanation_en)

    if st.button("Build my study plan from these results", type="primary"):
        try:
            build_study_plan(connection, student["id"], results.subject_id)
            st.success("Your study plan has been built from these diagnostic results.")
        except (ValueError, sqlite3.Error) as exc:
            show_friendly_error("Could not create your study plan.", _friendly_exception(exc, language))


def render_diagnostic(connection: sqlite3.Connection, student: dict[str, object], subject: sqlite3.Row | None) -> None:
    language = st.session_state.get("language", "en")
    st.header(tx(language, "diagnostic"))
    if subject is None:
        st.info(tx(language, "no_subject"))
        return

    session_key = st.session_state.get("diagnostic_session_key")
    if session_key is not None:
        session = connection.execute(
            """
            SELECT subject_id FROM diagnostic_sessions
            WHERE session_key = ? AND student_id = ?
            """,
            (session_key, student["id"]),
        ).fetchone()
        if session is None or session["subject_id"] != subject["id"]:
            st.session_state.pop("diagnostic_session_key", None)
            st.session_state.pop("last_diagnostic_result", None)
            session_key = None

    open_sessions = _open_diagnostic_sessions(connection, student["id"], subject["id"])
    if session_key is None and open_sessions:
        session = open_sessions[0]
        st.info(f"Unfinished diagnostic found · {session['status']} · updated {session['updated_at']}")
        if st.button(tx(language, "resume"), key="resume_latest"):
            try:
                if session["status"] == "paused":
                    resume_diagnostic(connection, session["session_key"], student["id"])
                st.session_state["diagnostic_session_key"] = session["session_key"]
                st.rerun()
            except (ValueError, sqlite3.Error) as exc:
                show_friendly_error("Could not resume this diagnostic.", _friendly_exception(exc, language))
        if len(open_sessions) > 1:
            session_key = st.selectbox(
                "Other unfinished test",
                [row["session_key"] for row in open_sessions],
                key="other_session_choice",
            )
            if st.button("Resume selected test"):
                try:
                    selected_row = next(row for row in open_sessions if row["session_key"] == session_key)
                    if selected_row["status"] == "paused":
                        resume_diagnostic(connection, session_key, student["id"])
                    st.session_state["diagnostic_session_key"] = session_key
                    st.rerun()
                except (ValueError, sqlite3.Error, StopIteration) as exc:
                    show_friendly_error("Could not resume this diagnostic.", _friendly_exception(exc, language))
    if session_key is None:
        latest_result = get_latest_diagnostic_result(
            connection,
            student["id"],
            subject["id"],
        )
        if latest_result is not None:
            _render_diagnostic_results(connection, student, latest_result)
        length = st.select_slider("Question count", options=[5, 10, 15], value=15)
        if st.button(tx(language, "start_test"), type="primary"):
            try:
                started = start_diagnostic(connection, student["id"], subject["id"], length)
                st.session_state["diagnostic_session_key"] = started["session_key"]
                st.session_state.pop("last_diagnostic_result", None)
                st.session_state.pop("question_started_at", None)
                st.rerun()
            except (ValueError, sqlite3.Error) as exc:
                show_friendly_error("Could not start the diagnostic.", _friendly_exception(exc, language))
        if not open_sessions:
            st.info(tx(language, "no_test"))
        return

    try:
        diagnostic = get_diagnostic(connection, session_key, student["id"])
    except (ValueError, sqlite3.Error) as exc:
        st.session_state.pop("diagnostic_session_key", None)
        show_friendly_error("Could not load the diagnostic.", _friendly_exception(exc, language))
        return

    answered = diagnostic["answered_count"]
    limit = diagnostic["question_limit"]
    if diagnostic["question_limit_adjusted"]:
        st.info(
            f"This subject has {limit // 2} topics, so the test was increased from "
            f"{diagnostic['requested_question_limit']} to {limit} questions to include "
            "at least two questions for every topic."
        )
    st.progress(answered / limit)
    st.caption(f"Question {min(answered + 1, limit)} of {limit} · {answered} answered")

    previous_result = st.session_state.get("last_diagnostic_result")
    if previous_result and previous_result.get("session_key") == session_key:
        if previous_result["is_correct"]:
            st.success("Correct!" if language == "en" else "సరైన సమాధానం!")
        else:
            st.error("Wrong" if language == "en" else "తప్పు")
        st.write(f"Your answer: {previous_result['student_answer']}")
        st.write(f"Correct answer: {previous_result['correct_answer']}")
        st.write(previous_result["explanation"])
        if st.button("Next", key=f"diagnostic_next_{session_key}", type="primary"):
            st.session_state.pop("last_diagnostic_result", None)
            st.rerun()
        return

    if diagnostic["status"] == "completed":
        try:
            results = get_diagnostic_results(connection, session_key, student["id"])
            _render_diagnostic_results(connection, student, results)
        except (ValueError, sqlite3.Error) as exc:
            show_friendly_error("Could not load the diagnostic results.", _friendly_exception(exc, language))
            return
        if st.button(tx(language, "new_test"), key=f"new_diagnostic_{session_key}"):
            st.session_state.pop("diagnostic_session_key", None)
            st.session_state.pop("last_diagnostic_result", None)
            st.rerun()
        return

    question = diagnostic["current_question"]
    if question is None:
        st.warning("No unanswered questions remain. Start a new diagnostic or review your plan.")
        st.session_state.pop("diagnostic_session_key", None)
        return
    question_token = f"{session_key}:{question['id']}"
    if st.session_state.get("question_timer_token") != question_token:
        st.session_state["question_timer_token"] = question_token
        st.session_state["question_started_at"] = time.monotonic()
    elapsed = max(0, int(time.monotonic() - st.session_state["question_started_at"]))
    st.caption(f"{question['topic_name']} · difficulty {question['difficulty']} · elapsed {elapsed}s")
    st.subheader(question["prompt"])

    with st.form(f"answer_form_{question['id']}"):
        option_keys = list(question["options"])
        selected_answer = st.radio(
            "Choose an answer",
            option_keys,
            format_func=lambda key: f"{key}. {question['options'][key]}",
        )
        submitted = st.form_submit_button(tx(language, "submit"), type="primary")
    if submitted:
        try:
            result = submit_answer(
                connection,
                session_key,
                student["id"],
                question["id"],
                selected_answer,
                elapsed,
            )
            st.session_state["last_diagnostic_result"] = {
                "session_key": session_key,
                "is_correct": result.is_correct,
                "student_answer": f"{result.student_answer}. {result.student_answer_text}",
                "correct_answer": f"{result.correct_answer}. {result.correct_answer_text}",
                "explanation": (
                    result.explanation_te or result.explanation_en
                    if language == "te"
                    else result.explanation_en
                ),
            }
            st.session_state.pop("question_timer_token", None)
            st.rerun()
        except (ValueError, sqlite3.Error) as exc:
            show_friendly_error("Could not save your answer.", _friendly_exception(exc, language))

    if st.button(tx(language, "pause_test"), key="pause_test"):
        try:
            pause_diagnostic(connection, session_key, student["id"])
            st.session_state.pop("diagnostic_session_key", None)
            st.success("Your progress is saved. Come back to resume.")
            st.rerun()
        except (ValueError, sqlite3.Error) as exc:
            show_friendly_error("Could not pause this diagnostic.", _friendly_exception(exc, language))


def _render_insight_status(insight: TopicInsight) -> None:
    st.markdown(
        status_badge(insight.status, insight.status.casefold()),
        unsafe_allow_html=True,
    )


def render_study_plan(connection: sqlite3.Connection, student: dict[str, object], subject: sqlite3.Row | None) -> None:
    language = st.session_state.get("language", "en")
    st.header(tx(language, "plan"))
    if subject is None:
        st.info(tx(language, "no_subject"))
        return
    latest_result = get_latest_diagnostic_result(
        connection,
        student["id"],
        subject["id"],
    )
    gate_message = diagnostic_plan_prompt(latest_result)
    if gate_message is not None:
        st.warning(tx(language, "diagnostic_first"))
        st.button(
            tx(language, "go_to_test"),
            type="primary",
            on_click=_navigate_to_diagnostic,
            args=(language,),
        )
    plan = get_active_study_plan(connection, student["id"], subject["id"])
    if plan is None:
        st.info(tx(language, "no_plan"))
    if latest_result is None and st.button(
        tx(language, "full_syllabus"),
        key=f"full_syllabus_{student['id']}_{subject['id']}",
    ):
        try:
            build_study_plan(
                connection,
                student["id"],
                subject["id"],
                full_syllabus=True,
            )
            st.rerun()
        except (ValueError, sqlite3.Error) as exc:
            show_friendly_error("Could not create your study plan.", _friendly_exception(exc, language))
            return
    if latest_result is not None and st.button(
        tx(language, "rebuild_plan"),
        key=f"refresh_plan_{student['id']}_{subject['id']}",
    ):
        try:
            plan = build_study_plan(connection, student["id"], subject["id"])
            st.rerun()
        except (ValueError, sqlite3.Error) as exc:
            show_friendly_error("Could not create your study plan.", _friendly_exception(exc, language))
            return
    if plan is None:
        return
    if plan.message:
        st.info(plan.message)
    st.caption(f"{plan_number_label(plan)} · {len(plan.tasks)} tasks")
    st.subheader("Why this plan")
    if plan.full_syllabus:
        st.write("Full-syllabus plan requested without diagnostic results.")
    else:
        st.write(f"Weak: {', '.join(plan.weak_topics) or 'None'}")
        st.write(f"Medium: {', '.join(plan.medium_topics) or 'None'}")
        st.write(f"Strong: {', '.join(plan.strong_topics) or 'None'}")

    for task in plan.tasks:
        columns = st.columns([5, 1])
        with columns[0]:
            st.checkbox(
                f"{task.scheduled_for} · {task.title} · {task.duration_minutes} min",
                value=task.is_completed,
                key=plan_task_widget_key(plan, task),
                on_change=_save_plan_task_checkbox,
                args=(
                    connection,
                    student["id"],
                    task.task_id,
                    plan_task_widget_key(plan, task),
                ),
            )
        with columns[1]:
            st.caption(task.task_type.title())
    insights = detect_weak_topics(connection, student["id"], subject["id"])
    planned_topic_keys = {task.topic_key for task in plan.tasks}
    weak_topics = [
        insight for insight in insights if insight.topic_key in planned_topic_keys
    ]
    st.subheader("Videos for topics to practice")
    if not weak_topics:
        st.info("No weak topics need a video recommendation yet.")
        return
    pack_directory = find_subject_pack_directory(subject["subject_key"])
    if pack_directory is None:
        st.info("Video resources are not configured for this subject yet.")
        return
    class_level = subject["class_level"]
    stream_name = subject["stream"] if "stream" in subject.keys() else ""
    for insight in weak_topics:
        entry = topic_video_entries(
            pack_directory,
            insight.topic_name,
            language=language,
        )
        render_topic_video(
            insight.topic_name,
            class_level,
            subject["name"],
            stream_name,
            entry,
        )


def _available_textbooks() -> list[Path]:
    if not TEXTBOOK_DIRECTORY.is_dir():
        return []
    return sorted(
        (
            path for path in TEXTBOOK_DIRECTORY.iterdir()
            if path.is_file() and path.suffix.casefold() in {".pdf", ".docx"}
        ),
        key=lambda path: path.name.casefold(),
    )


def _store_uploaded_textbook(uploaded_file) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(uploaded_file.name).name).strip("._")
    if not safe_name or Path(safe_name).suffix.casefold() not in {".pdf", ".docx"}:
        raise ValueError("Upload a PDF or DOCX textbook.")
    TEXTBOOK_DIRECTORY.mkdir(parents=True, exist_ok=True)
    target = TEXTBOOK_DIRECTORY / safe_name
    target.write_bytes(uploaded_file.getvalue())
    return target


def _index_and_retrieve(
    textbook_path: Path,
    query: str,
    settings: dict[str, object],
) -> tuple[RetrievalResult, str]:
    embedder = SentenceTransformerEmbeddings()
    index = index_textbook(
        textbook_path,
        chunk_size=settings["chunk_size"],
        overlap=settings["chunk_overlap"],
        cache_directory=DATA_DIRECTORY / "embeddings",
        embedder=embedder,
        start_page=settings.get("start_page", 1),
        end_page=settings.get("end_page"),
    )
    result = retrieve(
        query,
        index,
        embedder=embedder,
        top_k=settings["top_k"],
        similarity_threshold=settings["similarity_threshold"],
    )
    return result, index.source


def _textbook_is_indexed(textbook_path: Path | None, settings: dict[str, object]) -> bool:
    if textbook_path is None:
        return False
    try:
        key = textbook_cache_key(
            textbook_path,
            chunk_size=settings["chunk_size"],
            overlap=settings["chunk_overlap"],
            start_page=settings.get("start_page", 1),
            end_page=settings.get("end_page"),
        )
        return (DATA_DIRECTORY / "embeddings" / f"{key}.npz").is_file()
    except (OSError, ValueError):
        return False


def _index_worker(
    textbook_path: Path,
    settings: dict[str, object],
    progress_queue: queue.Queue,
    cancel_event: threading.Event,
) -> None:
    """Run indexing away from Streamlit's script thread."""
    try:
        embedder = SentenceTransformerEmbeddings()

        def report_progress(**progress: object) -> None:
            progress_queue.put(("progress", progress))

        index_textbook(
            textbook_path,
            chunk_size=settings["chunk_size"],
            overlap=settings["chunk_overlap"],
            cache_directory=DATA_DIRECTORY / "embeddings",
            embedder=embedder,
            start_page=settings.get("start_page", 1),
            end_page=settings.get("end_page"),
            batch_size=32,
            progress_callback=report_progress,
            cancel_event=cancel_event,
        )
        progress_queue.put(("done", None))
    except IndexingCancelled:
        progress_queue.put(("cancelled", None))
    except Exception as exc:
        logging.getLogger("learning_path").exception(
            "Textbook indexing failed for %s", textbook_path
        )
        progress_queue.put(("error", str(exc)))


@st.fragment(run_every="500ms")
def _render_indexing_job() -> None:
    """Poll indexing progress while leaving the rest of the app interactive."""
    job = st.session_state.get("textbook_index_job")
    if job is None:
        return
    progress_queue = job["queue"]
    while True:
        try:
            event, payload = progress_queue.get_nowait()
        except queue.Empty:
            break
        if event == "progress":
            job["progress"] = payload
        else:
            job["status"] = event
            job["error"] = payload

    progress = job.get("progress")
    if progress:
        total_pages = max(1, int(progress["total_pages"]))
        pages_done = min(total_pages, int(progress["pages_processed"]))
        total_chunks = int(progress["total_chunks"])
        chunks_done = int(progress["chunks_embedded"])
        if progress["stage"] in {"embed", "cached"} and total_chunks:
            fraction = 0.5 + 0.5 * chunks_done / total_chunks
        else:
            fraction = 0.5 * pages_done / total_pages
        st.progress(min(1.0, max(0.0, fraction)))
        st.caption(
            f"Pages processed: {pages_done}/{total_pages} · "
            f"Chunks embedded: {chunks_done}/{total_chunks or 'pending'}"
        )

    status = job.get("status", "running")
    if status == "running":
        if st.button("Cancel indexing", key="cancel_textbook_indexing"):
            job["cancel"].set()
            st.info("Cancelling after the current page or embedding batch…")
        else:
            st.info("Indexing textbook in the background…")
    elif status == "done":
        st.session_state.pop("textbook_index_job", None)
        st.rerun()
    elif status == "cancelled":
        st.warning("Indexing cancelled. The previous completed index, if any, was kept.")
        st.session_state.pop("textbook_index_job", None)
    elif status == "error":
        show_friendly_error("Could not index this textbook.", str(job.get("error") or "Please try again."))
        st.session_state.pop("textbook_index_job", None)


def _render_tutor_action(
    connection: sqlite3.Connection,
    subject: sqlite3.Row,
    topic: sqlite3.Row,
    textbook_path: Path | None,
    mode: str,
    question: str,
    settings: dict[str, object],
) -> None:
    language = st.session_state.get("language", "en")
    if textbook_path is None:
        retrieval = RetrievalResult(found=False, matches=(), message=NOT_FOUND_MESSAGE)
    else:
        if not _textbook_is_indexed(textbook_path, settings):
            st.info("Index this textbook before asking a question.")
            return
        try:
            retrieval, source = _index_and_retrieve(textbook_path, question, settings)
            st.caption(f"{source} · Indexed")
        except (EmbeddingError, DocumentLoadError, OSError, ValueError) as exc:
            show_friendly_error("Could not search this textbook.", _friendly_exception(exc, language))
            return

    st.session_state["tutor_retrieval"] = retrieval
    st.session_state["tutor_mode"] = mode
    if not retrieval.found or not retrieval.matches:
        st.info(retrieval.message or NOT_FOUND_MESSAGE)
        render_retrieved_chunks(retrieval, language)
        return

    try:
        response = tutor_response(
            connection,
            retrieval,
            topic_id=topic["id"],
            topic_key=topic["topic_key"],
            question=question,
            mode=mode,
            language=language,
            preferred_model=st.session_state.get("preferred_model"),
            temperature=settings["temperature"],
            question_bank_path=(
                find_subject_pack_directory(subject["subject_key"])
                or DATA_DIRECTORY / "question_bank.json"
            ),
        )
        st.session_state["tutor_response"] = response.text
        st.session_state["tutor_active_model"] = response.model_name
        st.markdown(response.text)
        st.caption(
            f"{response.source.title()} · {response.model_name or 'no model'}"
            + (" · cached" if response.cached else "")
        )
    except (OllamaError, NoModelAvailableError, TutorGenerationError, ValueError, sqlite3.Error) as exc:
        show_friendly_error("The tutor could not answer right now.", _friendly_exception(exc, language))
    render_retrieved_chunks(retrieval, language)


def render_tutor(connection: sqlite3.Connection, subject: sqlite3.Row | None) -> None:
    language = st.session_state.get("language", "en")
    st.header(tx(language, "tutor"))
    if subject is None:
        st.info(tx(language, "no_subject"))
        return
    topics = connection.execute(
        "SELECT id, topic_key, name FROM topics WHERE subject_id = ? ORDER BY sequence_number",
        (subject["id"],),
    ).fetchall()
    if not topics:
        st.info("No topics are available for this subject.")
        return
    settings = st.session_state.get(
        "app_settings",
        {
            "temperature": 0.2,
            "top_k": 3,
            "similarity_threshold": 0.35,
            "chunk_size": 900,
            "chunk_overlap": 120,
        },
    )
    topic_by_id = {row["id"]: row for row in topics}
    topic_id = st.selectbox(
        "Topic",
        list(topic_by_id),
        format_func=lambda row_id: topic_by_id[row_id]["name"],
        key=f"tutor_topic_{subject['id']}",
    )
    topic = topic_by_id[topic_id]
    books = _available_textbooks()
    if books:
        books_by_name = {path.name: path for path in books}
        selected_book_name = st.selectbox(
            tx(language, "select_book"),
            list(books_by_name),
            key="tutor_book",
        )
        book_path = books_by_name[selected_book_name]
    else:
        st.info(tx(language, "no_book"))
        book_path = None
    uploaded = st.file_uploader(
        tx(language, "upload_book"),
        type=["pdf", "docx"],
        key="tutor_upload",
    )
    if uploaded is not None:
        try:
            book_path = _store_uploaded_textbook(uploaded)
            st.success(f"Ready to index: {book_path.name}")
        except (OSError, ValueError) as exc:
            show_friendly_error("Could not save the uploaded textbook.", str(exc))
            book_path = None
    if book_path is not None:
        use_page_limit = st.checkbox(
            "Limit pages for quick testing",
            key=f"limit_textbook_pages_{book_path.name}",
        )
        if use_page_limit:
            settings["start_page"] = st.number_input(
                "First page",
                min_value=1,
                value=int(settings.get("start_page", 1)),
                step=1,
                key=f"index_start_page_{book_path.name}",
            )
            settings["end_page"] = st.number_input(
                "Last page",
                min_value=int(settings["start_page"]),
                value=max(
                    int(settings["start_page"]),
                    int(settings.get("end_page") or int(settings["start_page"]) + 99),
                ),
                step=1,
                key=f"index_end_page_{book_path.name}",
            )
        else:
            settings["start_page"] = 1
            settings["end_page"] = None
        index_status = "Indexed" if _textbook_is_indexed(book_path, settings) else "Not Indexed"
        index_tone = "strong" if index_status == "Indexed" else ""
        st.markdown(status_badge(index_status, index_tone), unsafe_allow_html=True)
        if st.button(
            "Index textbook" if index_status != "Indexed" else "Re-index textbook",
            key=f"start_textbook_index_{book_path.name}",
            disabled=(
                st.session_state.get("textbook_index_job") is not None
                and st.session_state["textbook_index_job"].get("status", "running") == "running"
            ),
        ):
            progress_queue: queue.Queue = queue.Queue()
            cancel_event = threading.Event()
            job = {
                "queue": progress_queue,
                "cancel": cancel_event,
                "progress": None,
                "status": "running",
                "error": None,
            }
            st.session_state["textbook_index_job"] = job
            worker = threading.Thread(
                target=_index_worker,
                args=(book_path, settings.copy(), progress_queue, cancel_event),
                daemon=True,
            )
            worker.start()
        if st.session_state.get("textbook_index_job") is not None:
            _render_indexing_job()

    tabs = st.tabs(["Explain", "Hint", "Practice"])
    modes = ("explain", "hint", "practice")
    for tab, mode in zip(tabs, modes):
        with tab:
            default_question = tutor_default_question(
                subject["name"], topic["name"], mode
            )
            with st.form(f"tutor_form_{mode}"):
                question = st.text_area(
                    tx(language, "question"),
                    value=default_question,
                    key=f"tutor_question_{subject['id']}_{topic['id']}_{mode}",
                    height=90,
                )
                submitted = st.form_submit_button(f"{mode.title()}", type="primary")
            if submitted:
                _render_tutor_action(
                    connection,
                    subject,
                    topic,
                    book_path,
                    mode,
                    question,
                    settings,
                )
            elif st.session_state.get("tutor_mode") == mode:
                retrieval = st.session_state.get("tutor_retrieval")
                response = st.session_state.get("tutor_response")
                if response:
                    st.markdown(response)
                if retrieval is not None:
                    render_retrieved_chunks(retrieval, language)


def render_settings(models: tuple[str, ...]) -> dict[str, object]:
    language = st.session_state.get("language", "en")
    st.header(tx(language, "settings"))
    if "app_settings" not in st.session_state:
        st.session_state["app_settings"] = {
            "temperature": 0.2,
            "top_k": 3,
            "similarity_threshold": 0.35,
            "chunk_size": 900,
            "chunk_overlap": 120,
        }
    settings = st.session_state["app_settings"]
    available = list(models)
    current_model = st.session_state.get("preferred_model")
    if current_model not in available:
        current_model = available[0] if available else None
    if available:
        selected_model = st.selectbox(
            tx(language, "model"),
            available,
            index=available.index(current_model) if current_model else 0,
        )
        st.session_state["preferred_model"] = selected_model
    else:
        st.info("No Ollama models found. Install one explicitly using `ollama pull llama3`.")

    settings["temperature"] = st.slider(
        tx(language, "temperature"), min_value=0.0, max_value=1.0,
        value=float(settings["temperature"]), step=0.05,
    )
    settings["top_k"] = st.slider(
        tx(language, "top_k"), min_value=1, max_value=8,
        value=int(settings["top_k"]),
    )
    settings["similarity_threshold"] = st.slider(
        tx(language, "threshold"), min_value=0.0, max_value=1.0,
        value=float(settings["similarity_threshold"]), step=0.05,
    )
    settings["chunk_size"] = st.slider(
        tx(language, "chunk_size"), min_value=200, max_value=2000,
        value=int(settings["chunk_size"]), step=50,
    )
    max_overlap = max(0, int(settings["chunk_size"]) - 1)
    settings["chunk_overlap"] = st.slider(
        tx(language, "overlap"), min_value=0, max_value=max_overlap,
        value=min(int(settings["chunk_overlap"]), max_overlap), step=10,
    )
    st.session_state["app_settings"] = settings
    st.info(tx(language, "settings_saved"))
    return settings


def render_student_page(
    connection: sqlite3.Connection,
    student: dict[str, object],
    subject: sqlite3.Row | None,
    page: str,
    models: tuple[str, ...],
) -> None:
    language = st.session_state.get("language", "en")
    if subject is not None:
        badge_text = draft_content_label(subject)
        if badge_text:
            st.markdown(
                status_badge(badge_text, "draft"),
                unsafe_allow_html=True,
            )
    if page == tx(language, "home"):
        render_home(connection, student, subject)
    elif page == tx(language, "diagnostic"):
        render_diagnostic(connection, student, subject)
    elif page == tx(language, "plan"):
        render_study_plan(connection, student, subject)
    elif page == tx(language, "tutor"):
        render_tutor(connection, subject)
    elif page == tx(language, "settings"):
        render_settings(models)
