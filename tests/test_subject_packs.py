import json
import shutil
from pathlib import Path

from core.diagnostic import start_diagnostic
from db.database import PROJECT_ROOT, get_connection, initialize_database
from db.seed import load_subject_packs, seed_all_subjects
from core.subject_videos import topic_video_entries, video_render_action
from scripts.build_curriculum_packs import write_pack
from scripts.validate_packs import validate_packs
from ui.student_view import ordered_class_levels, select_subjects_for_class


def test_all_subject_packs_load_and_have_six_questions_per_topic():
    packs = load_subject_packs()
    assert len(packs) == 95
    assert {pack["meta"]["class"] for pack in packs} >= {
        *(f"Class {grade}" for grade in range(1, 13)),
        "College",
    }
    assert sum(pack["meta"]["status"] == "complete" for pack in packs) == 2
    assert sum(pack["meta"]["status"] == "draft" for pack in packs) == 93
    for pack in packs:
        minimum = 6 if pack["meta"]["status"] == "complete" else 3
        assert all(
            sum(question["topic_key"] == topic["key"] for question in pack["bank"]["questions"]) >= minimum
            for topic in pack["bank"]["topics"]
        )


def test_core_math_science_and_college_packs_have_six_questions_per_topic():
    core_packs = [
        pack
        for pack in load_subject_packs()
        if pack["meta"]["class"] == "College"
        or (
            pack["meta"]["class"] in {f"Class {grade}" for grade in range(6, 11)}
            and pack["meta"]["subject"] in {"Mathematics", "Science"}
        )
    ]
    assert len(core_packs) == 20
    for pack in core_packs:
        topic_keys = {topic["key"] for topic in pack["bank"]["topics"]}
        assert all(
            sum(question["topic_key"] == topic_key for question in pack["bank"]["questions"]) >= 6
            for topic_key in topic_keys
        )


def test_class_ordering_and_class_stream_subject_filters(tmp_path):
    connection = get_connection(tmp_path / "class-filter.db")
    initialize_database(connection)
    seed_all_subjects(connection)
    classes = [
        row["class_level"]
        for row in connection.execute("SELECT DISTINCT class_level FROM subjects")
    ]
    assert ordered_class_levels(classes) == [
        *(f"Class {grade}" for grade in range(1, 13)),
        "College",
    ]
    grade8 = select_subjects_for_class(connection, "Class 8")
    assert {row["name"] for row in grade8} == {
        "English", "Mathematics", "Science", "Social Science", "Hindi", "Telugu"
    }
    science_stream = select_subjects_for_class(connection, "Class 11", "Science")
    assert {row["name"] for row in science_stream} == {
        "English", "Physics", "Chemistry", "Mathematics", "Biology", "Computer Science"
    }
    commerce = select_subjects_for_class(connection, "Class 11", "Commerce")
    assert {row["name"] for row in commerce} == {
        "English", "Accountancy", "Business Studies", "Economics"
    }
    assert select_subjects_for_class(connection, "Class 11", "Arts") != science_stream
    connection.close()


def test_seeding_is_repeatable_and_subject_data_stays_isolated(tmp_path):
    connection = get_connection(tmp_path / "packs.db")
    initialize_database(connection)
    assert seed_all_subjects(connection) == 95
    assert seed_all_subjects(connection) == 95
    rows = connection.execute(
        """
        SELECT s.subject_key, COUNT(DISTINCT t.id) AS topic_count,
               COUNT(DISTINCT q.id) AS question_count
        FROM subjects AS s
        JOIN topics AS t ON t.subject_id = s.id
        JOIN questions AS q ON q.subject_id = s.id
        GROUP BY s.id ORDER BY s.subject_key
        """
    ).fetchall()
    by_key = {row["subject_key"]: (row["topic_count"], row["question_count"]) for row in rows}
    assert by_key["class-8-mathematics"] == (10, 60)
    assert by_key["data-mining"] == (6, 36)
    assert by_key["dbms"] == (5, 40)

    connection.execute(
        "INSERT INTO students (username, password_hash, display_name, class_level) VALUES ('pack-test','hash','Pack Test','Class 8')"
    )
    connection.commit()
    subject_id = connection.execute(
        "SELECT id FROM subjects WHERE subject_key = 'class-8-mathematics'"
    ).fetchone()["id"]
    diagnostic = start_diagnostic(connection, 1, subject_id, question_limit=15)
    current_question = connection.execute(
        """
        SELECT s.subject_key, t.topic_key
        FROM questions AS q
        JOIN subjects AS s ON s.id = q.subject_id
        JOIN topics AS t ON t.id = q.topic_id
        WHERE q.id = ?
        """,
        (diagnostic["current_question"]["id"],),
    ).fetchone()
    assert current_question["subject_key"] == "class-8-mathematics"
    assert current_question["topic_key"] in {
        row["topic_key"]
        for row in connection.execute("SELECT topic_key FROM topics WHERE subject_id = ?", (subject_id,))
    }
    other_subject_id = connection.execute(
        "SELECT id FROM subjects WHERE subject_key = 'data-mining'"
    ).fetchone()["id"]
    assert other_subject_id != subject_id
    assert connection.execute(
        "SELECT COUNT(*) FROM questions WHERE subject_id = ? AND question_key LIKE '%data-mining%'",
        (subject_id,),
    ).fetchone()[0] == 0
    connection.close()


def test_pack_validator_reports_prerequisite_cycles(tmp_path):
    source = PROJECT_ROOT / "data" / "subjects"
    target = tmp_path / "subjects"
    shutil.copytree(source, target)
    topic_file = target / "College" / "data-mining" / "topics.json"
    catalog = json.loads(topic_file.read_text(encoding="utf-8"))
    catalog["topics"][0]["prerequisites"] = ["classification"]
    topic_file.write_text(json.dumps(catalog), encoding="utf-8")

    errors = validate_packs(target)
    assert any("circular prerequisite" in error for error in errors)


def test_pack_builder_removes_stale_video_topics_and_preserves_current_links(tmp_path):
    pack = tmp_path / "Class 1" / "mathematics"
    pack.mkdir(parents=True)
    (pack / "videos.json").write_text(
        json.dumps(
            {
                "videos": [
                    {
                        "topic": "Old Topic",
                        "title": "Outdated",
                        "source": "Legacy",
                        "url": None,
                        "duration_min": None,
                        "language": "en",
                        "verified": False,
                    },
                    {
                        "topic": "Current Topic",
                        "title": "Reviewed lesson",
                        "source": "Teacher",
                        "url": "https://www.youtube.com/watch?v=reviewed",
                        "duration_min": 8,
                        "language": "en",
                        "verified": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    write_pack(tmp_path, "Class 1", "Mathematics", ["Current Topic"], complete=False)
    videos = json.loads((pack / "videos.json").read_text(encoding="utf-8"))["videos"]

    assert [(video["topic"], video["language"]) for video in videos] == [
        ("Current Topic", "en"),
        ("Current Topic", "te"),
    ]
    assert videos[0]["verified"] is True
    assert videos[0]["url"] == "https://www.youtube.com/watch?v=reviewed"
    assert videos[1]["url"] is None


def test_subject_pack_video_catalogs_use_search_fallback_not_unverified_players():
    data_mining = PROJECT_ROOT / "data" / "subjects" / "College" / "data-mining"
    mathematics = PROJECT_ROOT / "data" / "subjects" / "Class 8" / "mathematics"
    data_mining_entry = topic_video_entries(data_mining, "Clustering")
    mathematics_entry = topic_video_entries(mathematics, "Fractions in Disguise")
    assert data_mining_entry is not None
    assert mathematics_entry is not None
    assert video_render_action(data_mining_entry) == ("search", None)
    assert video_render_action(mathematics_entry) == ("search", None)
