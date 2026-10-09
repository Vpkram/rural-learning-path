"""Build and persist prioritized, spaced study plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import sqlite3
from typing import Sequence

from core.diagnostic import get_latest_diagnostic_result
from core.weak_topics import TopicInsight, detect_weak_topics

TASK_DURATION_MINUTES = 10
REVISION_OFFSETS_DAYS = (1, 3, 6)


@dataclass(frozen=True)
class PlannedTask:
    topic_id: int
    topic_key: str
    topic_name: str
    title: str
    task_type: str
    duration_minutes: int
    scheduled_for: str
    sequence_number: int
    is_completed: bool = False
    task_id: int | None = None


@dataclass(frozen=True)
class StudyPlan:
    plan_id: int
    student_id: int
    subject_id: int
    generation: int
    status: str
    tasks: tuple[PlannedTask, ...]
    message: str | None = None
    weak_topics: tuple[str, ...] = ()
    medium_topics: tuple[str, ...] = ()
    strong_topics: tuple[str, ...] = ()
    full_syllabus: bool = False


def _topological_priority(
    insights: Sequence[TopicInsight],
    prerequisites: dict[int, set[int]],
    sequence_numbers: dict[int, int],
    priority_scores: dict[int, float] | None = None,
) -> list[TopicInsight]:
    """Sort weaker topics first while ensuring weak prerequisites come first."""
    by_id = {insight.topic_id: insight for insight in insights}
    in_scope = set(by_id)
    dependencies = {
        topic_id: prerequisites.get(topic_id, set()) & in_scope
        for topic_id in in_scope
    }
    ordered: list[TopicInsight] = []
    remaining = set(in_scope)
    while remaining:
        ready = [topic_id for topic_id in remaining if not (dependencies[topic_id] & remaining)]
        if not ready:
            names = sorted(by_id[topic_id].topic_name for topic_id in remaining)
            raise ValueError(f"Prerequisite graph contains a cycle among: {', '.join(names)}.")
        ready.sort(
            key=lambda topic_id: (
                -(
                    priority_scores[topic_id]
                    if priority_scores is not None and topic_id in priority_scores
                    else by_id[topic_id].weakness_score
                ),
                sequence_numbers.get(topic_id, 0),
                by_id[topic_id].topic_name.casefold(),
            )
        )
        next_id = ready[0]
        ordered.append(by_id[next_id])
        remaining.remove(next_id)
    return ordered


def _make_tasks(
    ordered_topics: Sequence[TopicInsight],
    start_date: date,
    days: int,
    labels: dict[int, str],
) -> list[PlannedTask]:
    if not ordered_topics:
        return []

    tasks: list[PlannedTask] = []
    last_day = days - 1
    for insight in ordered_topics:
        label = labels[insight.topic_id]
        if label == "Medium":
            activities = [
                ("practice", f"Practice {insight.topic_name}", 0),
                (
                    "revision",
                    f"Review {insight.topic_name} (spaced revision)",
                    min(3, last_day),
                ),
            ]
        else:
            revision_days: list[int] = []
            for offset in REVISION_OFFSETS_DAYS:
                day_offset = min(offset, last_day)
                if revision_days and day_offset <= revision_days[-1]:
                    continue
                revision_days.append(day_offset)
            activities = [
                ("lesson", f"Learn {insight.topic_name}", 0),
                ("example", f"Work through an example: {insight.topic_name}", 0),
                ("practice", f"Practice {insight.topic_name}", 0),
                *[
                    ("revision", f"Review {insight.topic_name} (spaced revision)", day_offset)
                    for day_offset in revision_days
                ],
            ]
        for task_type, title, day_offset in activities:
            tasks.append(
                PlannedTask(
                    topic_id=insight.topic_id,
                    topic_key=insight.topic_key,
                    topic_name=insight.topic_name,
                    title=title,
                    task_type=task_type,
                    duration_minutes=TASK_DURATION_MINUTES,
                    scheduled_for=(start_date + timedelta(days=day_offset)).isoformat(),
                    sequence_number=len(tasks),
                )
            )
    tasks.sort(key=lambda task: (task.scheduled_for, task.sequence_number))
    return [
        PlannedTask(
            topic_id=task.topic_id,
            topic_key=task.topic_key,
            topic_name=task.topic_name,
            title=task.title,
            task_type=task.task_type,
            duration_minutes=task.duration_minutes,
            scheduled_for=task.scheduled_for,
            sequence_number=sequence,
        )
        for sequence, task in enumerate(tasks)
    ]


def build_study_plan(
    connection: sqlite3.Connection,
    student_id: int,
    subject_id: int,
    *,
    days: int = 7,
    start_date: date | None = None,
    full_syllabus: bool = False,
) -> StudyPlan:
    """Rebuild and save a plan from the latest diagnostic or explicit fallback.

    Diagnostic-weak topics receive a full cycle, medium topics receive practice
    and one revision, and strong topics are skipped. Existing active plans are
    archived rather than deleted so their progress history remains available.
    """
    if isinstance(student_id, bool) or not isinstance(student_id, int) or student_id <= 0:
        raise ValueError("student_id must be a positive integer.")
    if isinstance(subject_id, bool) or not isinstance(subject_id, int) or subject_id <= 0:
        raise ValueError("subject_id must be a positive integer.")
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
        raise ValueError("days must be an integer between 1 and 30.")
    if not isinstance(full_syllabus, bool):
        raise ValueError("full_syllabus must be a boolean.")
    today = date.today()
    if start_date is not None and type(start_date) is not date:
        raise ValueError("start_date must be a date.")
    plan_start = max(start_date or today, today)

    if connection.execute("SELECT 1 FROM students WHERE id = ?", (student_id,)).fetchone() is None:
        raise ValueError("Student was not found.")
    if connection.execute(
        "SELECT 1 FROM subjects WHERE id = ?", (subject_id,)
    ).fetchone() is None:
        raise ValueError("Subject was not found.")

    all_topics = connection.execute(
        """
        SELECT id, topic_key, name, sequence_number
        FROM topics WHERE subject_id = ?
        ORDER BY sequence_number, id
        """,
        (subject_id,),
    ).fetchall()
    insights = detect_weak_topics(connection, student_id, subject_id)
    diagnostic = (
        None
        if full_syllabus
        else get_latest_diagnostic_result(connection, student_id, subject_id)
    )

    prerequisites: dict[int, set[int]] = {row["id"]: set() for row in all_topics}
    for row in connection.execute(
        """
        SELECT tp.topic_id, tp.prerequisite_topic_id
        FROM topic_prerequisites AS tp
        JOIN topics AS topic ON topic.id = tp.topic_id
        WHERE topic.subject_id = ?
        """,
        (subject_id,),
    ):
        prerequisites[row["topic_id"]].add(row["prerequisite_topic_id"])
    sequence_numbers = {row["id"]: row["sequence_number"] for row in all_topics}

    diagnostic_by_id = (
        {topic.topic_id: topic for topic in diagnostic.topics}
        if diagnostic is not None
        else {}
    )
    if diagnostic is not None:
        labels = {
            row["id"]: diagnostic_by_id[row["id"]].label
            for row in all_topics
        }
        weak = [
            insight for insight in insights
            if labels[insight.topic_id] == "Weak"
        ]
        medium = [
            insight for insight in insights
            if labels[insight.topic_id] == "Medium"
        ]
        weak_ordered = _topological_priority(
            weak,
            prerequisites,
            sequence_numbers,
            {
                topic.topic_id: 100.0 - topic.percentage
                for topic in diagnostic.topics
                if topic.label == "Weak"
            },
        )
        medium_ordered = sorted(
            medium,
            key=lambda insight: (
                sequence_numbers.get(insight.topic_id, 0),
                insight.topic_name.casefold(),
            ),
        )
        ordered = [*weak_ordered, *medium_ordered]
        snapshot_labels = labels
    elif full_syllabus:
        ordered = _topological_priority(insights, prerequisites, sequence_numbers)
        labels = {insight.topic_id: "Weak" for insight in insights}
        snapshot_labels = {row["id"]: "Full syllabus" for row in all_topics}
    else:
        selected = [insight for insight in insights if insight.status != "Strong"]
        ordered = _topological_priority(selected, prerequisites, sequence_numbers)
        labels = {
            insight.topic_id: ("Strong" if insight.status == "Strong" else "Weak")
            for insight in insights
        }
        snapshot_labels = {
            insight.topic_id: (
                "Strong"
                if insight.status == "Strong"
                else "Medium"
                if insight.status == "Developing"
                else "Weak"
            )
            for insight in insights
        }

    tasks = _make_tasks(ordered, plan_start, days, labels)
    selected = ordered

    connection.execute("SAVEPOINT rebuild_study_plan")
    try:
        connection.execute(
            """
            UPDATE study_plans SET status = 'archived'
            WHERE student_id = ? AND subject_id = ? AND status = 'active'
            """,
            (student_id, subject_id),
        )
        generation = connection.execute(
            """
            SELECT COALESCE(MAX(generation), 0) + 1
            FROM study_plans WHERE student_id = ? AND subject_id = ?
            """,
            (student_id, subject_id),
        ).fetchone()[0]
        cursor = connection.execute(
            """
            INSERT INTO study_plans (student_id, subject_id, generation, status)
            VALUES (?, ?, ?, 'active')
            """,
            (student_id, subject_id, generation),
        )
        plan_id = int(cursor.lastrowid)
        connection.executemany(
            """
            INSERT INTO study_plan_topics (
                plan_id, topic_id, label, questions_asked, correct_count, percentage
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    plan_id,
                    row["id"],
                    snapshot_labels[row["id"]],
                    (
                        diagnostic_by_id[row["id"]].questions_asked
                        if row["id"] in diagnostic_by_id
                        else None
                    ),
                    (
                        diagnostic_by_id[row["id"]].correct_count
                        if row["id"] in diagnostic_by_id
                        else None
                    ),
                    (
                        diagnostic_by_id[row["id"]].percentage
                        if row["id"] in diagnostic_by_id
                        else None
                    ),
                )
                for row in all_topics
            ],
        )
        connection.executemany(
            """
            INSERT INTO plan_tasks (
                plan_id, topic_id, title, task_type, duration_minutes,
                scheduled_for, sequence_number
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    plan_id,
                    task.topic_id,
                    task.title,
                    task.task_type,
                    task.duration_minutes,
                    task.scheduled_for,
                    task.sequence_number,
                )
                for task in tasks
            ],
        )
        connection.execute("RELEASE SAVEPOINT rebuild_study_plan")
        connection.commit()
    except BaseException:
        connection.execute("ROLLBACK TO SAVEPOINT rebuild_study_plan")
        connection.execute("RELEASE SAVEPOINT rebuild_study_plan")
        raise

    message = (
        "No weak or medium topics were found; your plan is clear for now."
        if not selected
        else None
    )
    saved_plan = get_active_study_plan(connection, student_id, subject_id)
    if saved_plan is None:
        raise RuntimeError("The newly saved study plan could not be loaded.")
    topic_names = {
        insight.topic_id: insight.topic_name for insight in insights
    }
    if full_syllabus:
        weak_names: tuple[str, ...] = ()
        medium_names: tuple[str, ...] = ()
        strong_names: tuple[str, ...] = ()
    else:
        weak_names = tuple(
            topic_names[topic_id]
            for topic_id, label in snapshot_labels.items()
            if label == "Weak"
        )
        medium_names = tuple(
            topic_names[topic_id]
            for topic_id, label in snapshot_labels.items()
            if label == "Medium"
        )
        strong_names = tuple(
            topic_names[topic_id]
            for topic_id, label in snapshot_labels.items()
            if label == "Strong"
        )
    return StudyPlan(
        plan_id=saved_plan.plan_id,
        student_id=saved_plan.student_id,
        subject_id=saved_plan.subject_id,
        generation=saved_plan.generation,
        status=saved_plan.status,
        tasks=saved_plan.tasks,
        message=message,
        weak_topics=weak_names,
        medium_topics=medium_names,
        strong_topics=strong_names,
        full_syllabus=full_syllabus,
    )


def get_active_study_plan(
    connection: sqlite3.Connection,
    student_id: int,
    subject_id: int,
) -> StudyPlan | None:
    """Load the latest active plan and its ordered tasks."""
    plan = connection.execute(
        """
        SELECT id, student_id, subject_id, generation, status
        FROM study_plans
        WHERE student_id = ? AND subject_id = ? AND status = 'active'
        ORDER BY generation DESC
        LIMIT 1
        """,
        (student_id, subject_id),
    ).fetchone()
    if plan is None:
        return None

    rows = connection.execute(
        """
        SELECT pt.id AS task_id, pt.topic_id, t.topic_key, t.name AS topic_name, pt.title,
               pt.task_type, pt.duration_minutes, pt.scheduled_for,
               pt.sequence_number, pt.is_completed
        FROM plan_tasks AS pt
        JOIN topics AS t ON t.id = pt.topic_id
        WHERE pt.plan_id = ?
        ORDER BY pt.scheduled_for, pt.sequence_number
        """,
        (plan["id"],),
    ).fetchall()
    topic_labels = connection.execute(
        """
        SELECT t.name, spt.label
        FROM study_plan_topics AS spt
        JOIN topics AS t ON t.id = spt.topic_id
        WHERE spt.plan_id = ?
        ORDER BY t.sequence_number, t.id
        """,
        (plan["id"],),
    ).fetchall()
    weak_topics = tuple(row["name"] for row in topic_labels if row["label"] == "Weak")
    medium_topics = tuple(row["name"] for row in topic_labels if row["label"] == "Medium")
    strong_topics = tuple(row["name"] for row in topic_labels if row["label"] == "Strong")
    full_syllabus = bool(topic_labels) and all(
        row["label"] == "Full syllabus" for row in topic_labels
    )
    tasks = tuple(
        PlannedTask(
            topic_id=row["topic_id"],
            topic_key=row["topic_key"],
            topic_name=row["topic_name"],
            title=row["title"],
            task_type=row["task_type"],
            duration_minutes=row["duration_minutes"],
            scheduled_for=row["scheduled_for"],
            sequence_number=row["sequence_number"],
            is_completed=bool(row["is_completed"]),
            task_id=row["task_id"],
        )
        for row in rows
    )
    return StudyPlan(
        plan_id=plan["id"],
        student_id=plan["student_id"],
        subject_id=plan["subject_id"],
        generation=plan["generation"],
        status=plan["status"],
        tasks=tasks,
        message="No tasks are scheduled yet." if not tasks else None,
        weak_topics=weak_topics,
        medium_topics=medium_topics,
        strong_topics=strong_topics,
        full_syllabus=full_syllabus,
    )


def complete_plan_task(
    connection: sqlite3.Connection,
    student_id: int,
    task_id: int,
) -> None:
    """Compatibility wrapper that marks one active plan task complete."""
    set_plan_task_completed(connection, student_id, task_id, True)


def set_plan_task_completed(
    connection: sqlite3.Connection,
    student_id: int,
    task_id: int,
    completed: bool,
) -> None:
    """Persist either direction of a learner's task checkbox."""
    if not isinstance(completed, bool):
        raise ValueError("completed must be a boolean.")
    cursor = connection.execute(
        """
        UPDATE plan_tasks
        SET is_completed = ?,
            completed_at = CASE
                WHEN ? = 1 THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                ELSE NULL
            END
        WHERE id = ?
          AND plan_id IN (
              SELECT id FROM study_plans
              WHERE student_id = ? AND status = 'active'
          )
        """,
        (int(completed), int(completed), task_id, student_id),
    )
    if cursor.rowcount != 1:
        raise ValueError("Active study-plan task was not found for this student.")
    connection.commit()
