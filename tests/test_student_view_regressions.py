from pathlib import Path

from ui.student_view import (
    draft_content_label,
    plan_number_label,
    plan_task_widget_key,
    render_topic_video,
    tutor_default_question,
)


def test_plan_label_uses_the_same_generation_number_everywhere():
    plan = type(
        "Plan",
        (),
        {"generation": 4, "plan_id": 28, "student_id": 3, "subject_id": 7},
    )()
    label = plan_number_label(plan)
    assert label == "Plan 4"
    assert label == plan_number_label(plan)
    task = type("Task", (), {"task_id": 91})()
    assert plan_task_widget_key(plan, task) == "task_3_7_28_91"


def test_tutor_prompt_tracks_selected_subject_topic_and_mode():
    assert tutor_default_question("Data Mining", "Clustering", "explain") == (
        "Explain Clustering in Data Mining using simple words."
    )
    assert tutor_default_question("Mathematics", "Fractions", "hint") == (
        "Give me a hint about Fractions in Mathematics."
    )


def test_progress_metric_uses_theme_aware_text_and_background_colors():
    styles = (Path(__file__).resolve().parent.parent / "ui" / "styles.py").read_text(encoding="utf-8")
    assert "var(--text-color)" in styles
    assert "var(--secondary-background-color)" in styles


def test_draft_badge_is_shown_only_for_draft_pack():
    assert draft_content_label({"content_status": "draft"}) == "Draft content · under review"
    assert draft_content_label({"content_status": "complete"}) is None


def test_video_rendering_never_creates_an_empty_player(monkeypatch):
    calls = []
    monkeypatch.setattr("ui.student_view.st.video", lambda value: calls.append(("video", value)))
    monkeypatch.setattr(
        "ui.student_view.st.link_button",
        lambda label, url: calls.append(("search", label, url)),
    )
    monkeypatch.setattr("ui.student_view.st.markdown", lambda value: None)
    monkeypatch.setattr("ui.student_view.st.caption", lambda value: None)

    render_topic_video(
        "Fractions",
        "Class 8",
        "Mathematics",
        "",
        {"url": None, "verified": False},
    )
    assert calls and calls[-1][0] == "search"
    assert not any(call[0] == "video" for call in calls)

    render_topic_video(
        "Fractions",
        "Class 8",
        "Mathematics",
        "",
        {
            "url": "https://www.youtube.com/watch?v=demo",
            "verified": True,
            "title": "Verified lesson",
            "duration_min": 12,
            "source": "Teacher",
        },
    )
    assert calls[-1] == ("video", "https://www.youtube.com/watch?v=demo")
