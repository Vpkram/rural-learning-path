"""Charts for completed diagnostic-test results."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping

import streamlit as st

from core.diagnostic import topic_label_for_percentage

WEAK_COLOR = "#d62728"
MEDIUM_COLOR = "#e6a700"
STRONG_COLOR = "#2ca02c"
LABEL_COLORS = {
    "Weak": WEAK_COLOR,
    "Medium": MEDIUM_COLOR,
    "Strong": STRONG_COLOR,
}

logger = logging.getLogger("learning_path")
NO_DATA_NOTICE = "There are no diagnostic answers to chart yet."
CHART_ERROR_NOTICE = "Charts are temporarily unavailable; your results are still shown above."


def _field(topic: object, name: str) -> object:
    if isinstance(topic, Mapping):
        return topic[name]
    return getattr(topic, name)


def color_for_label(label: str) -> str:
    """Return the established chart color for a diagnostic topic label."""
    return LABEL_COLORS[label]


def prepare_bar_data(topic_results: Iterable[object]) -> list[dict[str, str | float | int]]:
    """Normalize existing topic results and sort them from weakest to strongest."""
    rows = [
        {
            "topic_name": str(_field(topic, "topic_name")),
            "questions_asked": int(_field(topic, "questions_asked")),
            "correct_count": int(_field(topic, "correct_count")),
            "percentage": float(_field(topic, "percentage")),
            "label": str(_field(topic, "label")),
        }
        for topic in topic_results
    ]
    for row in rows:
        row["color"] = color_for_label(str(row["label"]))
    return sorted(
        rows,
        key=lambda row: (float(row["percentage"]), str(row["topic_name"]).casefold()),
    )


def remove_zero_value_slices(
    labels: Iterable[str],
    values: Iterable[int],
) -> tuple[list[str], list[int]]:
    """Remove zero-sized pie slices while preserving the input order."""
    nonzero = [
        (label, value)
        for label, value in zip(labels, values, strict=True)
        if value != 0
    ]
    return [label for label, _ in nonzero], [value for _, value in nonzero]


def prepare_pie_data(
    topic_results: Iterable[object],
) -> dict[str, list[str] | list[int]]:
    """Aggregate the supplied per-topic counts for the two result pies."""
    rows = prepare_bar_data(topic_results)
    asked = sum(int(row["questions_asked"]) for row in rows)
    correct = sum(int(row["correct_count"]) for row in rows)
    wrong = asked - correct
    overall_labels, overall_values = remove_zero_value_slices(
        ["Correct", "Wrong"],
        [correct, wrong],
    )

    label_counts = {
        label: sum(str(row["label"]) == label for row in rows)
        for label in LABEL_COLORS
    }
    topic_labels, topic_values = remove_zero_value_slices(
        list(label_counts),
        list(label_counts.values()),
    )
    return {
        "overall_labels": overall_labels,
        "overall_values": overall_values,
        "topic_labels": topic_labels,
        "topic_values": topic_values,
    }


def build_diagnostic_figures(
    topic_results: Iterable[object],
    text_color: str = "#262730",
) -> tuple[object, object, object]:
    """Build the topic bar chart and both pie charts without using Streamlit."""
    import plotly.graph_objects as go

    rows = prepare_bar_data(topic_results)
    pie_data = prepare_pie_data(rows)
    names = [str(row["topic_name"]) for row in rows]
    percentages = [float(row["percentage"]) for row in rows]
    colors = [str(row["color"]) for row in rows]
    customdata = [
        [int(row["correct_count"]), int(row["questions_asked"])]
        for row in rows
    ]
    horizontal = len(rows) > 6
    bar = go.Figure()
    if horizontal:
        bar.add_trace(
            go.Bar(
                x=percentages,
                y=names,
                orientation="h",
                marker_color=colors,
                text=[f"{value:.0f}%" for value in percentages],
                textposition="outside",
                cliponaxis=False,
                customdata=customdata,
                hovertemplate=(
                    "%{y}<br>%{x:.0f}% correct"
                    "<br>%{customdata[0]} / %{customdata[1]} correct"
                    "<extra></extra>"
                ),
            )
        )
        bar.update_xaxes(
            range=[0, 100],
            title_text="Percentage correct",
            color=text_color,
        )
        bar.update_yaxes(
            categoryorder="array",
            categoryarray=list(reversed(names)),
            color=text_color,
        )
    else:
        bar.add_trace(
            go.Bar(
                x=names,
                y=percentages,
                marker_color=colors,
                text=[f"{value:.0f}%" for value in percentages],
                textposition="outside",
                cliponaxis=False,
                customdata=customdata,
                hovertemplate=(
                    "%{x}<br>%{y:.0f}% correct"
                    "<br>%{customdata[0]} / %{customdata[1]} correct"
                    "<extra></extra>"
                ),
            )
        )
        bar.update_yaxes(
            range=[0, 100],
            title_text="Percentage correct",
            color=text_color,
        )
        bar.update_xaxes(color=text_color)
    bar.update_layout(
        title="Score by topic",
        showlegend=False,
        font={"color": text_color},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"t": 60, "b": 50, "l": 40, "r": 40},
        height=max(360, min(700, len(rows) * 48 + 150)) if horizontal else 360,
    )

    overall_values = pie_data["overall_values"]
    overall_labels = pie_data["overall_labels"]
    asked = sum(int(row["questions_asked"]) for row in rows)
    correct = sum(int(row["correct_count"]) for row in rows)
    overall = go.Figure(
        go.Pie(
            labels=overall_labels,
            values=overall_values,
            marker={"colors": [STRONG_COLOR if label == "Correct" else WEAK_COLOR for label in overall_labels]},
            hole=0.58,
            textinfo="label+percent",
            sort=False,
            hovertemplate="%{label}: %{value}<extra></extra>",
        )
    )
    overall.update_layout(
        title="Overall result",
        annotations=[
            {
                "text": f"{correct}/{asked}",
                "showarrow": False,
                "font": {"size": 20, "color": text_color},
            }
        ],
        font={"color": text_color},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"t": 55, "b": 20, "l": 20, "r": 20},
        height=300,
    )

    topic_labels = pie_data["topic_labels"]
    topic_values = pie_data["topic_values"]
    topic_levels = go.Figure(
        go.Pie(
            labels=topic_labels,
            values=topic_values,
            marker={"colors": [color_for_label(label) for label in topic_labels]},
            hole=0.42,
            textinfo="label+value",
            sort=False,
            hovertemplate="%{label}: %{value} topics<extra></extra>",
        )
    )
    topic_levels.update_layout(
        title="Topics by level",
        font={"color": text_color},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"t": 50, "b": 15, "l": 20, "r": 20},
        height=250,
    )
    return bar, overall, topic_levels


def _theme_text_color() -> str:
    theme_type = st.context.theme.get("type")
    theme_base = st.get_option("theme.base")
    if theme_type == "dark" or theme_base == "dark":
        return "#f0f2f6"
    return "#262730"


def render_diagnostic_charts(topic_results: Iterable[object]) -> str | None:
    """Render diagnostic charts from the topic results already shown on screen."""
    try:
        topics = tuple(topic_results)
        pie_data = prepare_pie_data(topics)
        if not topics or not pie_data["overall_values"]:
            st.info(NO_DATA_NOTICE)
            return NO_DATA_NOTICE
        if sum(pie_data["overall_values"]) == 0:
            st.info(NO_DATA_NOTICE)
            return NO_DATA_NOTICE

        bar, overall, topic_levels = build_diagnostic_figures(
            topics,
            text_color=_theme_text_color(),
        )
        columns = st.columns([1.4, 1], gap="large")
        with columns[0]:
            st.plotly_chart(
                bar,
                use_container_width=True,
                key="diagnostic_score_by_topic",
                theme="streamlit",
            )
            st.caption(
                "Percent correct for each topic, sorted from weakest to strongest; "
                "hover for correct answers out of questions asked."
            )
        with columns[1]:
            st.plotly_chart(
                overall,
                use_container_width=True,
                key="diagnostic_overall_result",
                theme="streamlit",
            )
            st.caption("Correct and wrong answers across the whole diagnostic test.")
            st.plotly_chart(
                topic_levels,
                use_container_width=True,
                key="diagnostic_topic_levels",
                theme="streamlit",
            )
            st.caption("Number of topics at each diagnostic level.")
    except Exception:
        logger.exception("Could not render diagnostic result charts.")
        st.info(CHART_ERROR_NOTICE)
        return CHART_ERROR_NOTICE
    return None
