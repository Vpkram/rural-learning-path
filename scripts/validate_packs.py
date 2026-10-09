"""Validate topic/question alignment and prerequisite graphs in subject packs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from db.seed import SUBJECT_PACKS_DIRECTORY, load_subject_packs
from scripts.build_curriculum_packs import expected_pack_directories


def validate_packs(directory: str | Path = SUBJECT_PACKS_DIRECTORY) -> list[str]:
    """Return actionable validation errors; an empty list means all packs pass."""
    try:
        packs = load_subject_packs(directory)
    except (OSError, ValueError) as exc:
        return [str(exc)]

    errors: list[str] = []
    root = Path(directory)
    for pack_directory in sorted(expected_pack_directories(root)):
        for filename in ("topics.json", "questions.json", "meta.json", "videos.json"):
            if not (pack_directory / filename).is_file():
                errors.append(f"{pack_directory}: missing required file {filename}.")

    global_question_keys: set[str] = set()
    for pack in packs:
        bank = pack["bank"]
        subject = bank["subject"]
        label = f"{subject['class_level']} / {subject['name']}"
        topic_keys = {topic["key"] for topic in bank["topics"]}
        graph_topics = {topic["key"]: topic for topic in pack["graph"]["topics"]}
        if set(graph_topics) != topic_keys:
            errors.append(f"{label}: topics.json and question catalog topics do not match.")

        for topic in bank["topics"]:
            for prerequisite in topic.get("prerequisites", []):
                if prerequisite not in topic_keys:
                    errors.append(f"{label}: {topic['key']} has unknown prerequisite {prerequisite}.")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visiting:
                errors.append(f"{label}: circular prerequisite involving {key}.")
                return
            if key in visited:
                return
            visiting.add(key)
            for prerequisite in graph_topics.get(key, {}).get("prerequisites", []):
                if prerequisite in topic_keys:
                    visit(prerequisite)
            visiting.remove(key)
            visited.add(key)

        for key in topic_keys:
            visit(key)

        questions_by_topic = {key: 0 for key in topic_keys}
        seen_prompts: set[str] = set()
        for question in bank["questions"]:
            key = question["key"]
            prompt = " ".join(question["prompt"].casefold().split())
            if key in global_question_keys:
                errors.append(f"{label}: duplicate question key {key}.")
            global_question_keys.add(key)
            if prompt in seen_prompts:
                errors.append(f"{label}: duplicate question prompt: {question['prompt']}")
            seen_prompts.add(prompt)
            topic_key = question["topic_key"]
            if topic_key not in topic_keys:
                errors.append(f"{label}: question {key} references unknown topic {topic_key}.")
                continue
            questions_by_topic[topic_key] += 1
            if not question.get("correct_answer") or not question.get("explanation"):
                errors.append(f"{label}: question {key} needs an answer and explanation.")
            explanation = question.get("explanation")
            if not isinstance(explanation, dict) or not isinstance(
                explanation.get("en"), str
            ) or not explanation["en"].strip():
                errors.append(f"{label}: question {key} needs an English explanation.")
        for topic_key, count in questions_by_topic.items():
            class_level = pack["meta"]["class"]
            subject_name = pack["meta"]["subject"]
            required_core_pack = class_level == "College" or (
                class_level in {f"Class {grade}" for grade in range(6, 11)}
                and subject_name in {"Mathematics", "Science"}
            )
            minimum = (
                6
                if pack["meta"]["status"] == "complete" or required_core_pack
                else 3
            )
            if count < minimum:
                errors.append(
                    f"{label}: topic {topic_key} has {count} questions; "
                    f"{pack['meta']['status']} packs require at least {minimum}."
                )
            difficulty_levels = {
                question["difficulty"]
                for question in bank["questions"]
                if question["topic_key"] == topic_key
            }
            if not any(level <= 2 for level in difficulty_levels) or not any(
                level >= 4 for level in difficulty_levels
            ):
                errors.append(f"{label}: topic {topic_key} needs easy and hard questions.")

        video_file = pack["directory"] / "videos.json"
        try:
            video_catalog = json.loads(video_file.read_text(encoding="utf-8"))
            video_entries = video_catalog.get("videos") if isinstance(video_catalog, dict) else None
            if not isinstance(video_entries, list):
                raise ValueError("videos.json must contain a videos list.")
            for entry in video_entries:
                required = {
                    "topic",
                    "title",
                    "source",
                    "url",
                    "duration_min",
                    "language",
                    "verified",
                }
                if not isinstance(entry, dict) or not required.issubset(entry):
                    errors.append(f"{label}: each video row must contain all required fields.")
                    continue
                if entry["topic"] not in {topic["name"] for topic in bank["topics"]}:
                    errors.append(f"{label}: video row references unknown topic {entry['topic']!r}.")
                if entry["language"] not in {"en", "te"} or not isinstance(entry["verified"], bool):
                    errors.append(f"{label}: video language or verified flag is invalid.")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{label}: could not validate videos.json: {exc}")

    return errors


def print_summary(directory: str | Path = SUBJECT_PACKS_DIRECTORY) -> None:
    """Print counts by class plus overall complete/draft counts."""
    packs = load_subject_packs(directory)
    by_class: dict[str, dict[str, int]] = {}
    for pack in packs:
        class_name = pack["meta"]["class"]
        row = by_class.setdefault(
            class_name,
            {"subjects": 0, "topics": 0, "questions": 0, "draft": 0},
        )
        row["subjects"] += 1
        row["topics"] += len(pack["bank"]["topics"])
        row["questions"] += len(pack["bank"]["questions"])
        row["draft"] += int(pack["meta"]["status"] == "draft")
    print("| Class | Subjects | Topics | Questions | Draft packs |")
    print("|---|---:|---:|---:|---:|")
    for class_name in sorted(by_class, key=_class_sort_key):
        values = by_class[class_name]
        print(
            f"| {class_name} | {values['subjects']} | {values['topics']} | "
            f"{values['questions']} | {values['draft']} |"
        )
    drafts = sum(row["draft"] for row in by_class.values())
    print(f"\nTotal packs: {len(packs)} · complete: {len(packs) - drafts} · draft: {drafts}")


def _class_sort_key(value: str) -> tuple[int, int | str]:
    if value.startswith("Class "):
        try:
            return (0, int(value.removeprefix("Class ")))
        except ValueError:
            pass
    return (1, value.casefold())


def main() -> int:
    errors = validate_packs()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print_summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
