from copy import deepcopy
from datetime import date, timedelta

import pytest

from core.diagnostic import (
    get_diagnostic_results,
    get_latest_diagnostic_result,
    start_diagnostic,
    submit_answer,
    topic_label_for_percentage,
)
from core.planner import build_study_plan, get_active_study_plan
from db.database import get_connection, initialize_database
from db.seed import load_question_bank, seed_database
from ui.student_view import diagnostic_plan_prompt, render_study_plan


def seeded_database(tmp_path):
    connection = get_connection(tmp_path / "diagnostic-plans.db")
    initialize_database(connection)
    seed_database(connection, load_question_bank())
    connection.execute(
        """
        INSERT INTO students (username, password_hash, display_name, class_level)
        VALUES ('diagnostic-learner', 'test-hash', 'Diagnostic Learner', 'College')
        """
    )
    connection.commit()
    subject_id = connection.execute(
        "SELECT id FROM subjects WHERE subject_key = 'dbms'"
    ).fetchone()["id"]
    return connection, subject_id


def complete_diagnostic(connection, subject_id, correct_by_topic):
    topic_count = connection.execute(
        "SELECT COUNT(*) FROM topics WHERE subject_id = ?",
        (subject_id,),
    ).fetchone()[0]
    session = start_diagnostic(
        connection,
        student_id=1,
        subject_id=subject_id,
        question_limit=2 * topic_count,
    )
    result = None
    answered_per_topic = {}
    question = session["current_question"]
    while question is not None:
        question_data = connection.execute(
            "SELECT correct_answer FROM questions WHERE id = ?",
            (question["id"],),
        ).fetchone()
        correct_answer = question_data["correct_answer"]
        question_number = answered_per_topic.get(question["topic_key"], 0)
        target_correct = correct_by_topic.get(question["topic_key"], 2)
        answer = (
            correct_answer
            if question_number < target_correct
            else next(key for key in question["options"] if key != correct_answer)
        )
        answered_per_topic[question["topic_key"]] = question_number + 1
        result = submit_answer(
            connection,
            session["session_key"],
            1,
            question["id"],
            answer,
            2,
        )
        question = result.next_question

    assert result is not None
    assert result.session_status == "completed"
    assert set(answered_per_topic.values()) == {2}
    return session["session_key"]


@pytest.mark.parametrize(
    ("percentage", "label"),
    [(49, "Weak"), (50, "Medium"), (79, "Medium"), (80, "Strong")],
)
def test_diagnostic_topic_labels_use_requested_thresholds(percentage, label):
    assert topic_label_for_percentage(percentage) == label


def test_answer_feedback_contains_the_checked_answer_and_explanation(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    session = start_diagnostic(connection, 1, subject_id, question_limit=10)
    question = session["current_question"]
    question_data = connection.execute(
        """
        SELECT correct_answer, options_json, explanation_en
        FROM questions WHERE id = ?
        """,
        (question["id"],),
    ).fetchone()
    result = submit_answer(
        connection,
        session["session_key"],
        1,
        question["id"],
        question_data["correct_answer"],
        1,
    )

    assert result.is_correct
    assert result.student_answer == question_data["correct_answer"]
    assert result.correct_answer == question_data["correct_answer"]
    assert result.correct_answer_text
    assert result.explanation_en == question_data["explanation_en"]
    assert result.next_question is not None


def test_completed_results_include_every_answer_and_persist_topic_scores(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    session_key = complete_diagnostic(
        connection,
        subject_id,
        {"database-basics": 1, "relational-model": 2},
    )
    results = get_diagnostic_results(connection, session_key, 1)

    assert results.subject_id == subject_id
    assert results.total_questions == 10
    assert results.correct_count == 9
    assert results.percentage == 90
    assert len(results.review) == results.total_questions
    assert all(item.student_answer_text for item in results.review)
    assert all(item.correct_answer_text and item.explanation_en for item in results.review)
    assert any(not item.is_correct for item in results.review)
    assert len(results.topics) == 5
    assert all(topic.questions_asked >= 2 for topic in results.topics)
    assert connection.execute(
        "SELECT COUNT(*) FROM diagnostic_topic_results WHERE session_id = ?",
        (session_key,),
    ).fetchone()[0] == 5


def test_diagnostic_raises_small_question_count_and_covers_each_subject_topic(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    session = start_diagnostic(connection, 1, subject_id, question_limit=5)
    assert session["requested_question_limit"] == 5
    assert session["question_limit"] == 10
    assert session["question_limit_adjusted"]

    session_key = complete_diagnostic(
        connection,
        subject_id,
        {},
    )
    asked = connection.execute(
        """
        SELECT t.topic_key, COUNT(*) AS count, MIN(q.subject_id) AS question_subject
        FROM attempts AS a
        JOIN questions AS q ON q.id = a.question_id
        JOIN topics AS t ON t.id = q.topic_id
        WHERE a.session_id = ? AND a.student_id = ? AND a.attempt_type = 'diagnostic'
        GROUP BY t.id
        """,
        (session_key, 1),
    ).fetchall()
    assert len(asked) == connection.execute(
        "SELECT COUNT(*) FROM topics WHERE subject_id = ?",
        (subject_id,),
    ).fetchone()[0]
    assert all(row["count"] >= 2 for row in asked)
    assert all(row["question_subject"] == subject_id for row in asked)


def test_diagnostic_plan_uses_weak_medium_and_strong_results_with_prerequisites(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    complete_diagnostic(
        connection,
        subject_id,
        {
            "database-basics": 0,
            "relational-model": 0,
            "sql-basics": 2,
            "normalization": 0,
            "transactions": 1,
        },
    )
    plan = get_active_study_plan(connection, 1, subject_id)
    assert plan is not None

    task_keys = {task.topic_key for task in plan.tasks}
    assert "sql-basics" not in task_keys
    assert "normalization" in task_keys
    assert plan.weak_topics == ("Database Basics", "Relational Model", "Normalization")
    assert plan.medium_topics == ("Transactions",)
    assert plan.strong_topics == ("SQL Basics",)

    weak_lessons = [
        task.topic_key for task in plan.tasks if task.task_type == "lesson"
    ]
    assert weak_lessons.index("database-basics") < weak_lessons.index("relational-model")
    assert weak_lessons.index("relational-model") < weak_lessons.index("normalization")
    assert {
        task.task_type for task in plan.tasks if task.topic_key == "transactions"
    } == {"practice", "revision"}
    assert {
        task.task_type for task in plan.tasks if task.topic_key == "database-basics"
    } == {"lesson", "example", "practice", "revision"}

    today_tasks = [task for task in plan.tasks if task.scheduled_for == date.today().isoformat()]
    weak_positions = [
        index for index, task in enumerate(today_tasks)
        if task.topic_key in {"database-basics", "relational-model", "normalization"}
    ]
    medium_positions = [
        index for index, task in enumerate(today_tasks)
        if task.topic_key == "transactions"
    ]
    assert max(weak_positions) < min(medium_positions)


def test_missing_diagnostic_gate_and_explicit_full_syllabus_option(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    assert get_latest_diagnostic_result(connection, 1, subject_id) is None
    assert diagnostic_plan_prompt(None) == (
        "Take the diagnostic test first so your plan matches your level"
    )

    plan = build_study_plan(
        connection,
        1,
        subject_id,
        full_syllabus=True,
        start_date=date.today() - timedelta(days=4),
    )
    expected_topic_ids = {
        row["id"]
        for row in connection.execute(
            "SELECT id FROM topics WHERE subject_id = ?",
            (subject_id,),
        )
    }
    assert plan.full_syllabus
    assert {task.topic_id for task in plan.tasks} == expected_topic_ids
    assert min(task.scheduled_for for task in plan.tasks) == date.today().isoformat()
    assert diagnostic_plan_prompt(get_latest_diagnostic_result(connection, 1, subject_id)) == (
        "Take the diagnostic test first so your plan matches your level"
    )


def test_study_plan_ui_shows_test_action_and_secondary_full_syllabus_option(
    tmp_path,
    monkeypatch,
):
    connection, subject_id = seeded_database(tmp_path)
    subject = connection.execute(
        "SELECT id, subject_key, name, class_level, stream FROM subjects WHERE id = ?",
        (subject_id,),
    ).fetchone()
    warnings = []
    buttons = []
    monkeypatch.setattr("ui.student_view.st.header", lambda *args, **kwargs: None)
    monkeypatch.setattr("ui.student_view.st.info", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "ui.student_view.st.warning",
        lambda message, **kwargs: warnings.append(message),
    )
    monkeypatch.setattr(
        "ui.student_view.st.button",
        lambda label, **kwargs: buttons.append((label, kwargs)) or False,
    )

    render_study_plan(connection, {"id": 1}, subject)

    assert warnings == [
        "Take the diagnostic test first so your plan matches your level"
    ]
    assert [label for label, _kwargs in buttons] == [
        "Go to diagnostic test",
        "Build a full-syllabus plan anyway",
    ]
    assert buttons[0][1]["on_click"] is not None
    assert buttons[1][1]["key"] == f"full_syllabus_1_{subject_id}"


def test_retake_and_refresh_use_the_latest_result_and_increment_plan_generation(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    complete_diagnostic(connection, subject_id, {})
    first_plan = get_active_study_plan(connection, 1, subject_id)
    assert first_plan is not None

    second_session = complete_diagnostic(
        connection,
        subject_id,
        {"database-basics": 0, "relational-model": 0},
    )
    latest = get_latest_diagnostic_result(connection, 1, subject_id)
    assert latest is not None
    assert latest.session_key == second_session
    assert next(topic for topic in latest.topics if topic.topic_key == "database-basics").label == "Weak"

    retake_plan = get_active_study_plan(connection, 1, subject_id)
    assert retake_plan is not None
    assert retake_plan.generation == first_plan.generation + 1
    refreshed = build_study_plan(connection, 1, subject_id)
    assert refreshed.generation == retake_plan.generation + 1
    assert refreshed.weak_topics[:2] == ("Database Basics", "Relational Model")


def test_latest_diagnostic_and_plan_are_isolated_by_subject(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    other_bank = deepcopy(load_question_bank())
    other_bank["subject"]["key"] = "other-college-subject"
    other_bank["subject"]["name"] = "Other College Subject"
    for question in other_bank["questions"]:
        question["key"] = f"other-{question['key']}"
    seed_database(connection, other_bank)
    other_subject_id = connection.execute(
        "SELECT id FROM subjects WHERE subject_key = 'other-college-subject'"
    ).fetchone()["id"]

    complete_diagnostic(connection, subject_id, {})
    assert get_latest_diagnostic_result(connection, 1, subject_id) is not None
    assert get_latest_diagnostic_result(connection, 1, other_subject_id) is None

    other_plan = build_study_plan(
        connection,
        1,
        other_subject_id,
        full_syllabus=True,
    )
    other_topic_ids = {
        row["id"]
        for row in connection.execute(
            "SELECT id FROM topics WHERE subject_id = ?",
            (other_subject_id,),
        )
    }
    assert other_plan.subject_id == other_subject_id
    assert {task.topic_id for task in other_plan.tasks} == other_topic_ids
    assert get_active_study_plan(connection, 1, subject_id).subject_id == subject_id
