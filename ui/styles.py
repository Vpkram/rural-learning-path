"""Lightweight, readable styling for small screens and classroom laptops."""

from __future__ import annotations

import streamlit as st


def apply_styles() -> None:
    """Apply high-contrast cards, readable text, and mobile-friendly spacing."""
    st.markdown(
        """
        <style>
        html, body, [class*="css"] {
            font-size: 17px;
        }
        .block-container {
            max-width: 1100px;
            padding-top: 1.2rem;
            padding-bottom: 3rem;
        }
        .status-badge {
            display: inline-block;
            border-radius: 999px;
            padding: 0.22rem 0.7rem;
            margin: 0.15rem 0.2rem 0.15rem 0;
            background: #e8eef7;
            color: #17324d;
            font-size: 0.88rem;
            font-weight: 650;
        }
        .status-weak { background: #fde8e7; color: #8f1d18; }
        .status-developing { background: #fff1cf; color: #704d00; }
        .status-strong { background: #e4f4e8; color: #155b2d; }
        .status-draft { background: #fff1cf; color: #704d00; }
        div[data-testid="stMetric"] {
            background: var(--secondary-background-color);
            color: var(--text-color);
            border: 1px solid var(--secondary-background-color);
            border-radius: 0.7rem;
            padding: 0.75rem;
        }
        div[data-testid="stMetric"] label,
        div[data-testid="stMetric"] [data-testid="stMetricValue"],
        div[data-testid="stMetric"] [data-testid="stMetricLabel"],
        div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
            color: var(--text-color) !important;
        }
        @media (max-width: 640px) {
            html, body, [class*="css"] { font-size: 16px; }
            .block-container { padding-left: 1rem; padding-right: 1rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def status_badge(label: str, tone: str = "") -> str:
    """Return markup for a concise visual status label."""
    allowed_tones = {"weak", "developing", "strong", "draft"}
    css_tone = f"status-{tone.casefold()}" if tone.casefold() in allowed_tones else ""
    return f'<span class="status-badge {css_tone}">{label}</span>'
