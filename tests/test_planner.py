from datetime import date, timedelta

import pytest

from core.planner import (
    build_study_plan,
    complete_plan_task,
    get_active_study_plan,
    set_plan_task_completed,
)
from db.database import get_connection, initialize_database
from db.seed import load_question_bank, seed_database
from core.weak_topics import detect_weak_topics


def seeded_database(tmp_path):
    connection = get_connection(tmp_path / "planner.db")
    initialize_database(connection)
    seed_database(connection, load_question_bank())
    connection.execute(
        """
        INSERT INTO students (username, password_hash, display_name, class_level)
        VALUES ('planner-learner', 'test-hash', 'Planner Learner', 'College')
        """
    )
    connection.commit()
    subject_id = connection.execute("SELECT id FROM subjects WHERE subject_key = 'dbms'").fetchone()[0]
    return connection, subject_id


def record_accuracy(connection, topic_key, correct, count=5):
    question_id = connection.execute(
        """
        SELECT q.id FROM questions AS q
        JOIN topics AS t ON t.id = q.topic_id
        WHERE t.topic_key = ?
        ORDER BY q.id LIMIT 1
        """,
        (topic_key,),
    ).fetchone()[0]
    for index in range(count):
        is_correct = int(index < correct)
        connection.execute(
            """
            INSERT INTO attempts (
                student_id, question_id, session_id, attempt_type, answer,
                is_correct, response_time_seconds, presented_difficulty
            ) VALUES (1, ?, ?, 'practice', 'A', ?, 10, 1)
            """,
            (question_id, f"{topic_key}-{index}", is_correct),
        )
    connection.commit()


def test_plan_prioritizes_weak_topics_but_respects_prerequisite_order(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    record_accuracy(connection, "database-basics", correct=0)
    record_accuracy(connection, "relational-model", correct=0)
    record_accuracy(connection, "sql-basics", correct=0)
    record_accuracy(connection, "normalization", correct=0)
    record_accuracy(connection, "transactions", correct=4)

    plan = build_study_plan(connection, 1, subject_id, start_date=date(2026, 10, 8))
    lesson_order = [
        task.topic_key for task in plan.tasks
        if task.task_type == "lesson"
    ]
    assert lesson_order.index("database-basics") < lesson_order.index("relational-model")
    assert lesson_order.index("relational-model") < lesson_order.index("sql-basics")
    assert lesson_order.index("sql-basics") < lesson_order.index("normalization")
    assert lesson_order[0] == "database-basics"


def test_plan_tasks_are_short_and_revision_dates_are_spaced(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    record_accuracy(connection, "database-basics", correct=0)
    plan = build_study_plan(connection, 1, subject_id, start_date=date(2026, 10, 8))

    assert plan.tasks
    assert all(task.task_id is not None for task in plan.tasks)
    assert all(5 <= task.duration_minutes <= 15 for task in plan.tasks)
    assert {task.task_type for task in plan.tasks} >= {"lesson", "example", "practice", "revision"}
    revisions = [
        date.fromisoformat(task.scheduled_for)
        for task in plan.tasks
        if task.topic_key == "database-basics" and task.task_type == "revision"
    ]
    assert len(revisions) == 3
    assert revisions == sorted(set(revisions))
    assert all((revision - date(2026, 10, 8)).days > 0 for revision in revisions)


def test_rebuilding_archives_old_plan_and_preserves_task_history(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    record_accuracy(connection, "database-basics", correct=0)
    first = build_study_plan(connection, 1, subject_id)
    first_task_id = connection.execute(
        "SELECT id FROM plan_tasks WHERE plan_id = ? ORDER BY id LIMIT 1", (first.plan_id,)
    ).fetchone()[0]
    complete_plan_task(connection, 1, first_task_id)

    second = build_study_plan(connection, 1, subject_id)
    old_status = connection.execute(
        "SELECT status FROM study_plans WHERE id = ?", (first.plan_id,)
    ).fetchone()[0]
    old_completion = connection.execute(
        "SELECT is_completed FROM plan_tasks WHERE id = ?", (first_task_id,)
    ).fetchone()[0]
    assert second.generation == first.generation + 1
    assert old_status == "archived"
    assert old_completion == 1
    assert get_active_study_plan(connection, 1, subject_id).plan_id == second.plan_id


def test_empty_plan_is_saved_with_helpful_message_when_all_topics_are_strong(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    for topic_key in ("database-basics", "relational-model", "sql-basics", "normalization", "transactions"):
        record_accuracy(connection, topic_key, correct=5, count=5)

    plan = build_study_plan(connection, 1, subject_id)
    assert plan.tasks == ()
    assert plan.message == "No weak or medium topics were found; your plan is clear for now."
    assert get_active_study_plan(connection, 1, subject_id).plan_id == plan.plan_id


def test_invalid_plan_parameters_and_task_owner_are_reported(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    with pytest.raises(ValueError, match="days"):
        build_study_plan(connection, 1, subject_id, days=0)
    with pytest.raises(ValueError, match="not found"):
        build_study_plan(connection, 99, subject_id)
    with pytest.raises(ValueError, match="not found"):
        complete_plan_task(connection, 99, 1)


def test_plan_checkbox_completion_can_be_toggled_and_updates_progress(tmp_path):
    connection, subject_id = seeded_database(tmp_path)
    plan = build_study_plan(connection, 1, subject_id)
    task = next(task for task in plan.tasks if task.topic_key == "database-basics")
    before = next(
        insight for insight in detect_weak_topics(connection, 1, subject_id)
        if insight.topic_key == task.topic_key
    )
    assert not task.is_completed
    assert before.mastery_score == 0.3

    set_plan_task_completed(connection, 1, task.task_id, True)
    persisted = connection.execute(
        "SELECT is_completed, completed_at FROM plan_tasks WHERE id = ?",
        (task.task_id,),
    ).fetchone()
    after = next(
        insight for insight in detect_weak_topics(connection, 1, subject_id)
        if insight.topic_key == task.topic_key
    )
    assert persisted["is_completed"] == 1
    assert persisted["completed_at"] is not None
    assert after.mastery_score > before.mastery_score

    set_plan_task_completed(connection, 1, task.task_id, False)
    persisted = connection.execute(
        "SELECT is_completed, completed_at FROM plan_tasks WHERE id = ?",
        (task.task_id,),
    ).fetchone()
    after_undo = next(
        insight for insight in detect_weak_topics(connection, 1, subject_id)
        if insight.topic_key == task.topic_key
    )
    assert persisted["is_completed"] == 0
    assert persisted["completed_at"] is None
    assert after_undo.mastery_score == before.mastery_score
