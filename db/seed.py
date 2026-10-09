"""Load the checked-in question bank into a local SQLite database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from db.database import DEFAULT_DATABASE_PATH, get_connection, initialize_database
else:
    from .database import DEFAULT_DATABASE_PATH, get_connection, initialize_database

QUESTION_BANK_PATH = Path(__file__).resolve().parent.parent / "data" / "question_bank.json"
TOPIC_GRAPH_PATH = Path(__file__).resolve().parent.parent / "data" / "topic_graph.json"
SUBJECT_PACKS_DIRECTORY = Path(__file__).resolve().parent.parent / "data" / "subjects"
ALLOWED_LANGUAGES = {"en", "te"}


def load_topic_graph(
    path: str | Path = TOPIC_GRAPH_PATH,
    question_bank: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load and verify graph topic names/keys against the question-bank catalog."""
    graph_path = Path(path)
    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read topic graph at {graph_path}: {exc}") from exc
    if not isinstance(graph, dict) or not isinstance(graph.get("topics"), list):
        raise ValueError("Topic graph must contain a topics list.")
    if question_bank is None:
        question_bank = load_question_bank()
    expected = {
        topic["key"]: topic["name"]
        for topic in question_bank["topics"]
    }
    graph_topics = graph["topics"]
    actual: dict[str, str] = {}
    for topic in graph_topics:
        if not isinstance(topic, dict) or not isinstance(topic.get("key"), str):
            raise ValueError("Every graph topic must have a string key.")
        key = topic["key"]
        name = topic.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Graph topic {key} must have a non-empty name.")
        if key in actual:
            raise ValueError(f"Duplicate graph topic key: {key}")
        actual[key] = name
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        mismatched = sorted(key for key in set(expected) & set(actual) if expected[key] != actual[key])
        raise ValueError(
            "Topic graph must match question-bank topic keys and exact names "
            f"(missing={missing}, extra={extra}, name_mismatches={mismatched})."
        )
    for topic in graph_topics:
        prerequisites = topic.get("prerequisites", [])
        if not isinstance(prerequisites, list) or any(
            not isinstance(item, str) or item not in expected for item in prerequisites
        ):
            raise ValueError(f"Topic {topic['key']} has an unknown or invalid prerequisite.")
        if topic["key"] in prerequisites:
            raise ValueError(f"Topic {topic['key']} cannot depend on itself.")
    return graph


def validate_question_bank(bank: dict[str, Any]) -> dict[str, Any]:
    """Validate a question bank before inserting any part of it into SQLite."""
    if not isinstance(bank, dict) or not isinstance(bank.get("subject"), dict):
        raise ValueError("Question bank must contain a subject object.")
    topics = bank.get("topics")
    questions = bank.get("questions")
    if not isinstance(topics, list) or not topics:
        raise ValueError("Question bank must contain at least one topic.")
    if not isinstance(questions, list) or not questions:
        raise ValueError("Question bank must contain at least one question.")

    topic_keys: set[str] = set()
    for topic in topics:
        if not isinstance(topic, dict) or not all(topic.get(key) for key in ("key", "name")):
            raise ValueError("Every topic must have a non-empty key and name.")
        if topic["key"] in topic_keys:
            raise ValueError(f"Duplicate topic key: {topic['key']}")
        topic_keys.add(topic["key"])

    question_keys: set[str] = set()
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError("Every question must be an object.")
        required = ("key", "topic_key", "prompt", "options", "correct_answer", "explanation")
        if any(not question.get(key) for key in required):
            raise ValueError("Every question must have a key, topic, prompt, options, answer, and explanations.")
        if question["key"] in question_keys:
            raise ValueError(f"Duplicate question key: {question['key']}")
        question_keys.add(question["key"])
        if question["topic_key"] not in topic_keys:
            raise ValueError(f"Question {question['key']} references an unknown topic.")
        difficulty = question.get("difficulty")
        if not isinstance(difficulty, int) or not 1 <= difficulty <= 5:
            raise ValueError(f"Question {question['key']} difficulty must be an integer from 1 to 5.")
        options = question["options"]
        explanations = question["explanation"]
        if not isinstance(options, dict) or len(options) < 2:
            raise ValueError(f"Question {question['key']} must have at least two keyed options.")
        if question["correct_answer"] not in options:
            raise ValueError(f"Question {question['key']} answer must match an option key.")
        if not isinstance(explanations, dict) or not isinstance(
            explanations.get("en"), str
        ) or not explanations["en"].strip():
            raise ValueError(f"Question {question['key']} needs an English explanation.")
        if "te" in explanations and (
            not isinstance(explanations["te"], str)
            or not explanations["te"].strip()
        ):
            raise ValueError(f"Question {question['key']} Telugu explanation cannot be empty.")

    subject = bank["subject"]
    if not all(subject.get(key) for key in ("key", "name", "class_level")):
        raise ValueError("Subject must have a non-empty key, name, and class_level.")
    return bank


def load_question_bank(path: str | Path = QUESTION_BANK_PATH) -> dict[str, Any]:
    """Read and minimally validate question-bank JSON before touching the DB."""
    bank_path = Path(path)
    try:
        bank = json.loads(bank_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read question bank at {bank_path}: {exc}") from exc
    return validate_question_bank(bank)


def load_subject_packs(
    directory: str | Path = SUBJECT_PACKS_DIRECTORY,
) -> list[dict[str, Any]]:
    """Discover subject packs from data/subjects/<class>/<subject>/."""
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"Subject packs directory does not exist: {root}")
    packs: list[dict[str, Any]] = []
    topic_files = set(root.glob("*/*/topics.json")) | set(root.glob("*/*/*/topics.json"))
    for topics_path in sorted(topic_files):
        pack_directory = topics_path.parent
        questions_path = pack_directory / "questions.json"
        meta_path = pack_directory / "meta.json"
        if not questions_path.is_file():
            raise ValueError(f"Subject pack is missing {questions_path.name}: {pack_directory}")
        if not meta_path.is_file():
            raise ValueError(f"Subject pack is missing {meta_path.name}: {pack_directory}")
        try:
            topic_catalog = json.loads(topics_path.read_text(encoding="utf-8"))
            question_catalog = json.loads(questions_path.read_text(encoding="utf-8"))
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read subject pack {pack_directory}: {exc}") from exc
        subject = topic_catalog.get("subject") if isinstance(topic_catalog, dict) else None
        topics = topic_catalog.get("topics") if isinstance(topic_catalog, dict) else None
        if not isinstance(subject, dict) or not isinstance(topics, list):
            raise ValueError(f"{topics_path} must contain subject and topics fields.")
        if not isinstance(metadata, dict):
            raise ValueError(f"{meta_path} must contain a JSON object.")
        required_meta = ("class", "subject", "board", "language", "status", "version")
        if any(not isinstance(metadata.get(field), str) or not metadata[field].strip() for field in required_meta):
            raise ValueError(f"{meta_path} must define class, subject, board, language, status, and version.")
        if metadata["status"] not in {"complete", "draft"}:
            raise ValueError(f"{meta_path} status must be complete or draft.")
        if metadata["class"] != subject["class_level"] or metadata["subject"] != subject["name"]:
            raise ValueError(f"{meta_path} class/subject must match topics.json.")
        if metadata["language"] != "en":
            raise ValueError(f"{meta_path} language must be en for this English-content catalog.")
        subject["stream"] = str(subject.get("stream", ""))
        if subject["class_level"] not in pack_directory.parts:
            raise ValueError(f"Pack directory {pack_directory} does not match class {subject['class_level']}.")
        if isinstance(question_catalog, dict) and isinstance(question_catalog.get("source"), str):
            source_path = (pack_directory / question_catalog["source"]).resolve()
            try:
                referenced_catalog = json.loads(source_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"Could not read question source {source_path}: {exc}") from exc
            questions = referenced_catalog.get("questions") if isinstance(referenced_catalog, dict) else None
        elif isinstance(question_catalog, dict):
            questions = question_catalog.get("questions")
        else:
            questions = question_catalog
        bank = validate_question_bank(
            {"subject": subject, "topics": topics, "questions": questions}
        )
        graph = {
            "subject": subject["key"],
            "topics": [
                {
                    "key": topic["key"],
                    "name": topic["name"],
                    "prerequisites": topic.get("prerequisites", []),
                }
                for topic in topics
            ],
        }
        load_topic_graph_from_data(graph, bank)
        bank["meta"] = metadata
        packs.append({"bank": bank, "graph": graph, "directory": pack_directory, "meta": metadata})
    if not packs:
        raise ValueError(f"No subject packs with topics.json were found in {root}.")
    keys = [pack["bank"]["subject"]["key"] for pack in packs]
    if len(keys) != len(set(keys)):
        raise ValueError("Subject pack keys must be unique.")
    return packs


def find_subject_pack_directory(
    subject_key: str,
    directory: str | Path = SUBJECT_PACKS_DIRECTORY,
) -> Path | None:
    """Find the folder owning a database subject key."""
    root = Path(directory)
    topic_files = set(root.glob("*/*/topics.json")) | set(root.glob("*/*/*/topics.json"))
    for topics_path in sorted(topic_files):
        try:
            topic_catalog = json.loads(topics_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read subject topic catalog {topics_path}: {exc}") from exc
        subject = topic_catalog.get("subject") if isinstance(topic_catalog, dict) else None
        if isinstance(subject, dict) and subject.get("key") == subject_key:
            return topics_path.parent
    return None


def load_topic_graph_from_data(
    graph: dict[str, Any],
    question_bank: dict[str, Any],
) -> dict[str, Any]:
    """Validate a graph already assembled from a subject pack."""
    expected = {topic["key"]: topic["name"] for topic in question_bank["topics"]}
    actual = {
        item["key"]: item.get("name")
        for item in graph.get("topics", [])
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    }
    if actual != expected:
        raise ValueError("Subject pack topic graph must match the topic keys and names.")
    for item in graph["topics"]:
        prerequisites = item.get("prerequisites", [])
        if not isinstance(prerequisites, list) or any(
            not isinstance(key, str) or key not in expected for key in prerequisites
        ):
            raise ValueError(f"Topic {item['key']} has an unknown or invalid prerequisite.")
    return graph


def seed_all_subjects(
    connection: sqlite3.Connection,
    directory: str | Path = SUBJECT_PACKS_DIRECTORY,
) -> int:
    """Idempotently seed every discovered class/subject pack."""
    packs = load_subject_packs(directory)
    connection.execute("SAVEPOINT seed_all_subject_packs")
    try:
        for pack in packs:
            seed_database(connection, pack["bank"], pack["graph"], commit=False)
        connection.execute("RELEASE SAVEPOINT seed_all_subject_packs")
        connection.commit()
    except BaseException:
        connection.execute("ROLLBACK TO SAVEPOINT seed_all_subject_packs")
        connection.execute("RELEASE SAVEPOINT seed_all_subject_packs")
        raise
    return len(packs)


def seed_database(
    connection: sqlite3.Connection,
    bank: dict[str, Any],
    graph: dict[str, Any] | None = None,
    *,
    commit: bool = True,
) -> None:
    """Insert/update only catalog content; never remove a learner's records."""
    active_graph = graph if graph is not None else load_topic_graph(question_bank=bank)
    subject = bank["subject"]
    metadata = bank.get("meta", {})
    connection.execute(
        """
        INSERT INTO subjects (
            subject_key, name, class_level, description, stream, content_status
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(subject_key) DO UPDATE SET
            name = excluded.name,
            class_level = excluded.class_level,
            description = excluded.description,
            stream = excluded.stream,
            content_status = excluded.content_status
        """,
        (
            subject["key"],
            subject["name"],
            subject["class_level"],
            subject.get("description", ""),
            subject.get("stream", ""),
            metadata.get("status", "complete"),
        ),
    )
    subject_id = connection.execute(
        "SELECT id FROM subjects WHERE subject_key = ?", (subject["key"],)
    ).fetchone()["id"]

    topic_ids: dict[str, int] = {}
    for topic in bank["topics"]:
        connection.execute(
            """
            INSERT INTO topics (subject_id, topic_key, name, description, sequence_number)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(subject_id, topic_key) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                sequence_number = excluded.sequence_number
            """,
            (
                subject_id,
                topic["key"],
                topic["name"],
                topic.get("description", ""),
                topic.get("sequence_number", 0),
            ),
        )
        row = connection.execute(
            "SELECT id FROM topics WHERE subject_id = ? AND topic_key = ?",
            (subject_id, topic["key"]),
        ).fetchone()
        topic_ids[topic["key"]] = row["id"]

    connection.execute(
        """
        DELETE FROM topic_prerequisites
        WHERE topic_id IN (SELECT id FROM topics WHERE subject_id = ?)
        """,
        (subject_id,),
    )
    for topic in active_graph["topics"]:
        for prerequisite_key in topic.get("prerequisites", []):
            connection.execute(
                """
                INSERT INTO topic_prerequisites (topic_id, prerequisite_topic_id)
                VALUES (?, ?)
                """,
                (topic_ids[topic["key"]], topic_ids[prerequisite_key]),
            )

    for question in bank["questions"]:
        connection.execute(
            """
            INSERT INTO questions (
                question_key, subject_id, topic_id, difficulty, prompt,
                options_json, correct_answer, explanation_en, explanation_te, active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(question_key) DO UPDATE SET
                subject_id = excluded.subject_id,
                topic_id = excluded.topic_id,
                difficulty = excluded.difficulty,
                prompt = excluded.prompt,
                options_json = excluded.options_json,
                correct_answer = excluded.correct_answer,
                explanation_en = excluded.explanation_en,
                explanation_te = excluded.explanation_te,
                active = excluded.active
            """,
            (
                question["key"],
                subject_id,
                topic_ids[question["topic_key"]],
                question["difficulty"],
                question["prompt"],
                json.dumps(question["options"], ensure_ascii=False),
                question["correct_answer"],
                question["explanation"]["en"],
                question["explanation"].get("te", ""),
                int(question.get("active", True)),
            ),
        )
    if commit:
        connection.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize and seed the local learning database.")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=f"SQLite file path (default: {DEFAULT_DATABASE_PATH})",
    )
    parser.add_argument(
        "--bank",
        type=Path,
        default=None,
        help="Seed one legacy question bank instead of all discovered subject packs.",
    )
    parser.add_argument(
        "--graph",
        type=Path,
        default=None,
        help="Topic graph for --bank; otherwise all discovered subject packs are loaded.",
    )
    args = parser.parse_args()
    with get_connection(args.db) as connection:
        initialize_database(connection)
        if args.bank is not None:
            bank = load_question_bank(args.bank)
            graph = load_topic_graph(
                args.graph or TOPIC_GRAPH_PATH,
                question_bank=bank,
            )
            seed_database(connection, bank, graph)
            loaded_subjects = 1
            total_topics = len(bank["topics"])
            total_questions = len(bank["questions"])
        else:
            packs = load_subject_packs()
            seed_all_subjects(connection)
            loaded_subjects = len(packs)
            total_topics = sum(len(pack["bank"]["topics"]) for pack in packs)
            total_questions = sum(len(pack["bank"]["questions"]) for pack in packs)
    print(f"Database ready: {args.db}")
    print(
        f"Loaded {loaded_subjects} subjects, {total_topics} topics, "
        f"and {total_questions} questions."
    )


if __name__ == "__main__":
    main()
