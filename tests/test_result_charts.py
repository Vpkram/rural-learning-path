from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from core.diagnostic import topic_label_for_percentage
from ui import result_charts


def topic(name, asked, correct, percentage, label):
    return SimpleNamespace(
        topic_name=name,
        questions_asked=asked,
        correct_count=correct,
        percentage=percentage,
        label=label,
    )


def test_bar_data_is_sorted_weakest_to_strongest_and_preserves_counts():
    rows = result_charts.prepare_bar_data(
        [
            topic("Strong topic", 4, 4, 100, "Strong"),
            topic("Weak topic", 4, 1, 25, "Weak"),
            topic("Medium topic", 4, 3, 75, "Medium"),
        ]
    )

    assert [row["topic_name"] for row in rows] == [
        "Weak topic",
        "Medium topic",
        "Strong topic",
    ]
    assert (rows[0]["correct_count"], rows[0]["questions_asked"]) == (1, 4)
    assert rows[0]["color"] == result_charts.WEAK_COLOR


@pytest.mark.parametrize(
    ("percentage", "label", "expected_color"),
    [
        (49, "Weak", result_charts.WEAK_COLOR),
        (50, "Medium", result_charts.MEDIUM_COLOR),
        (79, "Medium", result_charts.MEDIUM_COLOR),
        (80, "Strong", result_charts.STRONG_COLOR),
    ],
)
def test_label_colors_follow_existing_diagnostic_thresholds(
    percentage,
    label,
    expected_color,
):
    assert topic_label_for_percentage(percentage) == label
    assert result_charts.color_for_label(label) == expected_color


def test_pie_data_counts_answers_and_topic_levels():
    data = result_charts.prepare_pie_data(
        [
            topic("A", 4, 1, 25, "Weak"),
            topic("B", 4, 2, 50, "Medium"),
            topic("C", 4, 4, 100, "Strong"),
            topic("D", 4, 3, 75, "Medium"),
        ]
    )

    assert data == {
        "overall_labels": ["Correct", "Wrong"],
        "overall_values": [10, 6],
        "topic_labels": ["Weak", "Medium", "Strong"],
        "topic_values": [1, 2, 1],
    }


def test_zero_value_pie_slices_are_removed():
    assert result_charts.remove_zero_value_slices(
        ["Correct", "Wrong"],
        [5, 0],
    ) == (["Correct"], [5])


@pytest.mark.parametrize(
    "topics",
    [
        [
            topic("Fractions", 4, 2, 50, "Medium"),
            topic("Geometry", 3, 1, 33.3, "Weak"),
        ],
        [topic("Fractions", 4, 2, 50, "Medium")],
        [topic("Fractions", 4, 4, 100, "Strong")],
        [topic("Fractions", 4, 0, 0, "Weak")],
        [],
    ],
    ids=["normal", "one-topic", "all-correct", "all-wrong", "empty"],
)
def test_figures_build_without_streamlit_for_supported_result_shapes(topics):
    bar, overall, topic_levels = result_charts.build_diagnostic_figures(topics)

    assert len(bar.data) == 1
    assert len(overall.data) == 1
    assert len(topic_levels.data) == 1


def test_bar_chart_becomes_horizontal_after_six_topics():
    topics = [
        topic(f"Topic {index}", 2, index % 2, index * 10, "Weak")
        for index in range(7)
    ]

    bar, _, _ = result_charts.build_diagnostic_figures(topics)

    assert bar.data[0].orientation == "h"


def test_empty_diagnostic_render_shows_friendly_notice(monkeypatch):
    notices = []
    monkeypatch.setattr(result_charts.st, "info", notices.append)

    notice = result_charts.render_diagnostic_charts([])

    assert notice == result_charts.NO_DATA_NOTICE
    assert notices == [result_charts.NO_DATA_NOTICE]


def test_successful_render_uses_distinct_keys_and_accessible_captions(monkeypatch):
    charts = []
    captions = []
    monkeypatch.setattr(
        result_charts.st,
        "columns",
        lambda *args, **kwargs: [nullcontext(), nullcontext()],
    )
    monkeypatch.setattr(
        result_charts.st,
        "plotly_chart",
        lambda figure, **kwargs: charts.append(kwargs),
    )
    monkeypatch.setattr(result_charts.st, "caption", captions.append)
    monkeypatch.setattr(result_charts, "_theme_text_color", lambda: "#262730")

    notice = result_charts.render_diagnostic_charts(
        [topic("Fractions", 4, 2, 50, "Medium")]
    )

    assert notice is None
    assert [chart["key"] for chart in charts] == [
        "diagnostic_score_by_topic",
        "diagnostic_overall_result",
        "diagnostic_topic_levels",
    ]
    assert all(chart["use_container_width"] for chart in charts)
    assert len(captions) == 3


def test_chart_failure_is_logged_and_returns_notice(monkeypatch, caplog):
    notices = []

    def fail_to_build(*args, **kwargs):
        raise RuntimeError("plotly render failed")

    monkeypatch.setattr(result_charts, "build_diagnostic_figures", fail_to_build)
    monkeypatch.setattr(result_charts.st, "info", notices.append)
    monkeypatch.setattr(result_charts, "_theme_text_color", lambda: "#262730")

    with caplog.at_level("ERROR", logger="learning_path"):
        notice = result_charts.render_diagnostic_charts(
            [topic("Fractions", 4, 2, 50, "Medium")]
        )

    assert notice == result_charts.CHART_ERROR_NOTICE
    assert notices == [result_charts.CHART_ERROR_NOTICE]
    assert "Could not render diagnostic result charts." in caplog.text
