"""Read, validate, and look up language-aware topic video resources."""

from __future__ import annotations

from dataclasses import dataclass
import csv
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

from db.seed import load_question_bank, load_topic_graph
from core.weak_topics import TopicInsight

DEFAULT_VIDEO_CSV = Path(__file__).resolve().parent.parent / "data" / "videos.csv"
VIDEO_FIELDS = ("subject", "topic", "language", "title", "url", "duration_min", "level")
SUPPORTED_LANGUAGES = ("en", "te")


class VideoDataError(ValueError):
    """The video CSV cannot be read or does not have the required structure."""


@dataclass(frozen=True)
class VideoRecommendation:
    subject: str
    topic: str
    language: str
    title: str | None
    url: str | None
    duration_min: int | None
    level: str | None
    requested_language: str
    fallback_used: bool = False
    warning: str | None = None


@dataclass(frozen=True)
class VideoValidationReport:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    missing_topics: tuple[str, ...]
    missing_languages: tuple[str, ...]
    invalid_links: tuple[str, ...]


def _valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
    )


def _read_video_rows(csv_path: str | Path) -> list[dict[str, str]]:
    path = Path(csv_path)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            headers = tuple(reader.fieldnames or ())
            missing_fields = [field for field in VIDEO_FIELDS if field not in headers]
            if missing_fields:
                raise VideoDataError(
                    f"Video CSV is missing required columns: {', '.join(missing_fields)}."
                )
            rows: list[dict[str, str]] = []
            for line_number, row in enumerate(reader, start=2):
                if None in row:
                    raise VideoDataError(f"Video CSV has too many columns on line {line_number}.")
                rows.append(
                    {
                        field: (row.get(field) or "").strip()
                        for field in VIDEO_FIELDS
                    }
                )
            return rows
    except FileNotFoundError as exc:
        raise VideoDataError(f"Video CSV was not found: {path}") from exc
    except OSError as exc:
        raise VideoDataError(f"Could not read video CSV {path}: {exc}") from exc
    except csv.Error as exc:
        raise VideoDataError(f"Could not parse video CSV {path}: {exc}") from exc


def _catalog_topics(
    question_bank_path: str | Path,
    topic_graph_path: str | Path,
) -> tuple[str, dict[str, str]]:
    bank = load_question_bank(question_bank_path)
    graph = load_topic_graph(topic_graph_path, question_bank=bank)
    topic_names = {topic["key"]: topic["name"] for topic in bank["topics"]}
    graph_names = {topic["key"]: topic["name"] for topic in graph["topics"]}
    if graph_names != topic_names:
        raise VideoDataError("Topic names in the graph do not exactly match the question bank.")
    return bank["subject"]["key"], topic_names


def recommend_videos(
    topics: list[str] | tuple[str, ...],
    *,
    subject: str = "dbms",
    language: str = "en",
    csv_path: str | Path = DEFAULT_VIDEO_CSV,
) -> list[VideoRecommendation]:
    """Return one recommendation per topic, falling back from Telugu to English.

    If a row has an invalid or missing URL, return an explicit warning instead
    of a broken link. A missing CSV is raised as VideoDataError for the caller
    to render as a friendly UI message.
    """
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError("language must be en or te.")
    rows = _read_video_rows(csv_path)
    recommendations: list[VideoRecommendation] = []
    for topic in topics:
        candidates = [
            row for row in rows
            if row["subject"].casefold() == subject.casefold()
            and row["topic"] == topic
        ]
        selected_language = language
        matching = [row for row in candidates if row["language"].casefold() == language]
        fallback_used = False
        if not matching and language == "te":
            matching = [row for row in candidates if row["language"].casefold() == "en"]
            selected_language = "en"
            fallback_used = bool(matching)

        if not matching:
            recommendations.append(
                VideoRecommendation(
                    subject=subject,
                    topic=topic,
                    language=language,
                    title=None,
                    url=None,
                    duration_min=None,
                    level=None,
                    requested_language=language,
                    warning=f"No {language} or fallback English video is available for {topic}.",
                )
            )
            continue

        row = matching[0]
        if not row["url"] or not _valid_url(row["url"]):
            recommendations.append(
                VideoRecommendation(
                    subject=subject,
                    topic=topic,
                    language=selected_language,
                    title=row["title"] or None,
                    url=None,
                    duration_min=None,
                    level=row["level"] or None,
                    requested_language=language,
                    fallback_used=fallback_used,
                    warning=f"The video link for {topic} is missing or invalid.",
                )
            )
            continue
        try:
            duration = int(row["duration_min"])
        except ValueError:
            duration = None
        recommendations.append(
            VideoRecommendation(
                subject=subject,
                topic=topic,
                language=selected_language,
                title=row["title"] or None,
                url=row["url"],
                duration_min=duration,
                level=row["level"] or None,
                requested_language=language,
                fallback_used=fallback_used,
            )
        )
    return recommendations


def recommend_weak_topic_videos(
    weak_topics: Sequence[TopicInsight],
    *,
    subject: str = "dbms",
    language: str = "en",
    csv_path: str | Path = DEFAULT_VIDEO_CSV,
) -> list[VideoRecommendation]:
    """Look up recommendations for the weak/developing insights directly."""
    return recommend_videos(
        [insight.topic_name for insight in weak_topics if insight.status != "Strong"],
        subject=subject,
        language=language,
        csv_path=csv_path,
    )


def validate_video_csv(
    csv_path: str | Path = DEFAULT_VIDEO_CSV,
    *,
    question_bank_path: str | Path | None = None,
    topic_graph_path: str | Path | None = None,
) -> VideoValidationReport:
    """Validate headers, topic-name parity, language coverage, and video URLs."""
    base_directory = Path(csv_path).resolve().parent
    bank_path = Path(question_bank_path) if question_bank_path is not None else base_directory / "question_bank.json"
    graph_path = Path(topic_graph_path) if topic_graph_path is not None else base_directory / "topic_graph.json"
    errors: list[str] = []
    warnings: list[str] = []
    missing_topics: list[str] = []
    missing_languages: list[str] = []
    invalid_links: list[str] = []

    try:
        expected_subject, topic_names = _catalog_topics(bank_path, graph_path)
    except ValueError as exc:
        errors.append(str(exc))
        return VideoValidationReport(False, tuple(errors), (), (), (), ())

    try:
        rows = _read_video_rows(csv_path)
    except VideoDataError as exc:
        return VideoValidationReport(False, (str(exc),), (), (), (), ())

    relevant_rows = [row for row in rows if row["subject"].casefold() == expected_subject.casefold()]
    topics_present = {row["topic"] for row in relevant_rows if row["topic"]}
    missing_topics = sorted(name for name in topic_names.values() if name not in topics_present)
    for topic_name in missing_topics:
        errors.append(f"Missing video topic: {topic_name}.")

    for topic_name in topic_names.values():
        topic_rows = [row for row in relevant_rows if row["topic"] == topic_name]
        languages_present = {row["language"].casefold() for row in topic_rows}
        for language in SUPPORTED_LANGUAGES:
            if language not in languages_present:
                missing_languages.append(f"{topic_name}:{language}")
                warnings.append(f"Missing {language} video for {topic_name}.")

    topic_keys_by_name = {name: key for key, name in topic_names.items()}
    for line_number, row in enumerate(rows, start=2):
        label = f"line {line_number} ({row['topic'] or 'unnamed topic'})"
        if row["subject"].casefold() != expected_subject.casefold():
            continue
        if row["topic"] not in topic_keys_by_name:
            errors.append(f"{label} has a topic name not found exactly in question_bank.json/topic_graph.json.")
        if row["language"].casefold() not in SUPPORTED_LANGUAGES:
            errors.append(f"{label} has unsupported language '{row['language']}'.")
        if not row["title"]:
            errors.append(f"{label} is missing a title.")
        if not row["url"] or not _valid_url(row["url"]):
            invalid_links.append(label)
            errors.append(f"{label} has a missing or invalid http(s) URL.")
        try:
            duration = int(row["duration_min"])
            if duration <= 0:
                raise ValueError
        except ValueError:
            errors.append(f"{label} must have a positive integer duration_min.")
        if not row["level"]:
            errors.append(f"{label} is missing a level.")

    return VideoValidationReport(
        valid=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        missing_topics=tuple(missing_topics),
        missing_languages=tuple(missing_languages),
        invalid_links=tuple(invalid_links),
    )
