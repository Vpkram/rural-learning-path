"""Topic-level weakness estimates using accuracy, speed, and recent trend."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True)
class TopicInsight:
    topic_id: int
    topic_key: str
    topic_name: str
    mastery_score: float
    accuracy: float | None
    average_response_seconds: float | None
    recent_accuracy_trend: float | None
    weakness_score: float
    status: str
    root_cause_topic_keys: tuple[str, ...]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, value))


def _status_for_weakness(score: float, has_attempts: bool) -> str:
    if not has_attempts:
        return "Developing"
    if score >= 0.65:
        return "Weak"
    if score >= 0.35:
        return "Developing"
    return "Strong"


def detect_weak_topics(
    connection: sqlite3.Connection,
    student_id: int,
    subject_id: int,
) -> list[TopicInsight]:
    """Combine answer accuracy, relative response time, and recent trend.

    The speed measure compares a topic's average answer time with the
    student's own median, avoiding a fixed assumption about typing speed.
    """
    topics = connection.execute(
        """
        SELECT t.id, t.topic_key, t.name, t.sequence_number,
               MAX(
                   COALESCE(m.score, 0.30),
                   CASE WHEN task_progress.total > 0
                       THEN 0.30 + 0.70 * task_progress.completed / task_progress.total
                       ELSE COALESCE(m.score, 0.30)
                   END
               ) AS mastery_score
        FROM topics AS t
        LEFT JOIN mastery AS m ON m.topic_id = t.id AND m.student_id = ?
        LEFT JOIN (
            SELECT pt.topic_id, COUNT(*) AS total,
                   SUM(CASE WHEN pt.is_completed = 1 THEN 1 ELSE 0 END) AS completed
            FROM plan_tasks AS pt
            JOIN study_plans AS sp ON sp.id = pt.plan_id
            WHERE sp.student_id = ? AND sp.subject_id = ? AND sp.status = 'active'
            GROUP BY pt.topic_id
        ) AS task_progress ON task_progress.topic_id = t.id
        WHERE t.subject_id = ?
        ORDER BY t.sequence_number, t.id
        """,
        (student_id, student_id, subject_id, subject_id),
    ).fetchall()
    if not topics:
        return []

    attempts = connection.execute(
        """
        SELECT q.topic_id, a.is_correct, a.response_time_seconds, a.answered_at, a.id
        FROM attempts AS a
        JOIN questions AS q ON q.id = a.question_id
        WHERE a.student_id = ? AND q.subject_id = ?
        ORDER BY a.answered_at DESC, a.id DESC
        """,
        (student_id, subject_id),
    ).fetchall()

    by_topic: dict[int, list[sqlite3.Row]] = {topic["id"]: [] for topic in topics}
    all_times = [float(attempt["response_time_seconds"]) for attempt in attempts]
    for attempt in attempts:
        by_topic.setdefault(attempt["topic_id"], []).append(attempt)

    sorted_times = sorted(all_times)
    if not sorted_times:
        median_time = 0.0
    elif len(sorted_times) % 2:
        median_time = sorted_times[len(sorted_times) // 2]
    else:
        middle = len(sorted_times) // 2
        median_time = (sorted_times[middle - 1] + sorted_times[middle]) / 2

    metrics: dict[int, tuple[float | None, float | None, float | None, float]] = {}
    for topic in topics:
        topic_attempts = by_topic[topic["id"]]
        if not topic_attempts:
            metrics[topic["id"]] = (None, None, None, 1.0 - topic["mastery_score"])
            continue

        accuracy = sum(attempt["is_correct"] for attempt in topic_attempts) / len(topic_attempts)
        average_time = sum(float(a["response_time_seconds"]) for a in topic_attempts) / len(topic_attempts)
        recent = topic_attempts[:3]
        previous = topic_attempts[3:6]
        trend = None
        if recent and previous:
            recent_accuracy = sum(a["is_correct"] for a in recent) / len(recent)
            previous_accuracy = sum(a["is_correct"] for a in previous) / len(previous)
            trend = recent_accuracy - previous_accuracy

        if median_time <= 0:
            slowdown = 0.0
        else:
            slowdown = _clamp((average_time / median_time) - 1.0)
        decline = _clamp(-(trend or 0.0))
        weakness = _clamp(0.65 * (1.0 - accuracy) + 0.20 * slowdown + 0.15 * decline)
        metrics[topic["id"]] = (accuracy, average_time, trend, weakness)

    topic_keys = {topic["id"]: topic["topic_key"] for topic in topics}
    weak_ids = {
        topic["id"]
        for topic in topics
        if _status_for_weakness(metrics[topic["id"]][3], bool(by_topic[topic["id"]])) == "Weak"
    }
    prerequisites: dict[int, set[int]] = {topic["id"]: set() for topic in topics}
    for relation in connection.execute(
        """
        SELECT prerequisite.topic_id, prerequisite.prerequisite_topic_id
        FROM topic_prerequisites AS prerequisite
        JOIN topics AS child ON child.id = prerequisite.topic_id
        WHERE child.subject_id = ?
        """,
        (subject_id,),
    ):
        prerequisites.setdefault(relation["topic_id"], set()).add(
            relation["prerequisite_topic_id"]
        )

    def weak_ancestors(topic_id: int) -> tuple[str, ...]:
        found: set[int] = set()
        visited: set[int] = set()
        pending = list(prerequisites.get(topic_id, ()))
        while pending:
            prerequisite_id = pending.pop()
            if prerequisite_id in visited:
                continue
            visited.add(prerequisite_id)
            if prerequisite_id in weak_ids:
                found.add(prerequisite_id)
            pending.extend(prerequisites.get(prerequisite_id, ()))
        return tuple(sorted(topic_keys[item] for item in found))

    insights: list[TopicInsight] = []
    for topic in topics:
        accuracy, average_time, trend, weakness = metrics[topic["id"]]
        insights.append(
            TopicInsight(
                topic_id=topic["id"],
                topic_key=topic["topic_key"],
                topic_name=topic["name"],
                mastery_score=topic["mastery_score"],
                accuracy=accuracy,
                average_response_seconds=average_time,
                recent_accuracy_trend=trend,
                weakness_score=weakness,
                status=_status_for_weakness(weakness, bool(by_topic[topic["id"]])),
                root_cause_topic_keys=weak_ancestors(topic["id"]),
            )
        )
    return sorted(insights, key=lambda insight: (-insight.weakness_score, insight.topic_name))
