"""Shared Streamlit components for app status, error handling, and tutor context."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import streamlit as st

from llm.model_selector import ModelSelector, NoModelAvailableError
from llm.ollama_client import OllamaClient, OllamaConnectionError, OllamaError
from rag.models import RetrievalResult
from ui.styles import status_badge

T = TypeVar("T")


def render_header(language: str, ollama: OllamaClient) -> tuple[tuple[str, ...], str | None]:
    """Show the app title, connection badge, and currently selected local model."""
    st.title("Rural Learning Path" if language == "en" else "గ్రామీణ అభ్యాస మార్గం")
    models: tuple[str, ...] = ()
    status = "Not Connected"
    try:
        models = ollama.list_models()
        status = "Connected"
    except OllamaError:
        pass

    try:
        selection = ModelSelector().select(
            models,
            st.session_state.get("preferred_model"),
        )
        active_model = st.session_state.get("preferred_model")
        if active_model not in selection.available_models:
            active_model = selection.active_model
            st.session_state["preferred_model"] = active_model
    except NoModelAvailableError:
        active_model = None

    left, right = st.columns([3, 2])
    with left:
        model_label = (
            f"Active model: {active_model}"
            if active_model
            else "No model installed · ollama pull llama3"
        )
        st.markdown(status_badge(model_label), unsafe_allow_html=True)
    with right:
        display_status = status if language == "en" else (
            "కనెక్ట్ అయింది" if status == "Connected" else "కనెక్ట్ కాలేదు"
        )
        st.markdown(status_badge(display_status), unsafe_allow_html=True)
    return models, active_model


def show_friendly_error(message: str, details: str | None = None) -> None:
    """Render a concise user-facing error without displaying a traceback."""
    st.error(message)
    if details:
        with st.expander("Troubleshooting"):
            st.write(details)


def guarded_ui_action(action: Callable[[], T], *, message: str) -> T | None:
    """Run a page action while converting expected failures to friendly UI text."""
    try:
        return action()
    except (OllamaError, ValueError, OSError) as exc:
        show_friendly_error(message, str(exc))
        return None


def render_retrieved_chunks(retrieval: RetrievalResult, language: str = "en") -> None:
    """Show the exact evidence and scores passed to the tutor."""
    title = "Retrieved textbook evidence" if language == "en" else "పాఠ్యపుస్తకం నుంచి పొందిన సమాచారం"
    with st.expander(title, expanded=False):
        if not retrieval.found or not retrieval.matches:
            st.info(retrieval.message or "This topic was not found in the textbook.")
            return
        for index, match in enumerate(retrieval.matches, start=1):
            page = f"page {match.chunk.page_number}" if match.chunk.page_number is not None else "page unavailable"
            st.caption(
                f"{index}. {match.chunk.source} · {page} · similarity {match.similarity:.3f}"
            )
            st.write(match.chunk.text)
            if index < len(retrieval.matches):
                st.divider()
