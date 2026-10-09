import csv

import pytest

from core.video_recommender import (
    VideoDataError,
    recommend_videos,
    validate_video_csv,
)
from db.seed import QUESTION_BANK_PATH, TOPIC_GRAPH_PATH


def test_recommender_finds_language_specific_video_and_english_fallback(tmp_path):
    rows = [
        ["dbms", "Database Basics", "en", "English Basics", "https://example.org/en", "10", "Beginner"],
        ["dbms", "Database Basics", "te", "Telugu Basics", "https://example.org/te", "11", "Beginner"],
        ["dbms", "Transactions", "en", "English Transactions", "https://example.org/tx", "12", "Intermediate"],
    ]
    path = tmp_path / "videos.csv"
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["subject", "topic", "language", "title", "url", "duration_min", "level"])
        writer.writerows(rows)

    results = recommend_videos(
        ["Database Basics", "Transactions"],
        language="te",
        csv_path=path,
    )
    assert results[0].language == "te"
    assert results[0].url == "https://example.org/te"
    assert not results[0].fallback_used
    assert results[1].language == "en"
    assert results[1].fallback_used
    assert results[1].url == "https://example.org/tx"


def test_recommender_handles_missing_csv_and_missing_links(tmp_path):
    with pytest.raises(VideoDataError, match="not found"):
        recommend_videos(["Database Basics"], csv_path=tmp_path / "missing.csv")

    path = tmp_path / "videos.csv"
    path.write_text(
        "subject,topic,language,title,url,duration_min,level\n"
        "dbms,Database Basics,en,Missing link,,10,Beginner\n",
        encoding="utf-8",
    )
    result = recommend_videos(["Database Basics"], csv_path=path)[0]
    assert result.url is None
    assert "missing or invalid" in result.warning


def test_validator_accepts_shipped_csv_and_exact_topic_names():
    report = validate_video_csv(
        question_bank_path=QUESTION_BANK_PATH,
        topic_graph_path=TOPIC_GRAPH_PATH,
    )
    assert report.valid
    assert report.missing_topics == ()
    assert report.missing_languages == ()
    assert report.invalid_links == ()


def test_validator_flags_missing_topics_languages_invalid_links_and_name_mismatch(tmp_path):
    (tmp_path / "question_bank.json").write_text(
        QUESTION_BANK_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "topic_graph.json").write_text(
        TOPIC_GRAPH_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    path = tmp_path / "videos.csv"
    path.write_text(
        "subject,topic,language,title,url,duration_min,level\n"
        "dbms,Database Basics,en,Basics,not-a-url,10,Beginner\n"
        "dbms,Wrong topic name,en,Wrong title,https://example.org,10,Beginner\n",
        encoding="utf-8",
    )
    report = validate_video_csv(path)
    assert not report.valid
    assert "SQL Basics" in report.missing_topics
    assert "Database Basics:te" in report.missing_languages
    assert report.invalid_links
    assert any("not found exactly" in error for error in report.errors)


def test_validator_reports_missing_csv_without_throwing(tmp_path):
    report = validate_video_csv(
        tmp_path / "missing.csv",
        question_bank_path=QUESTION_BANK_PATH,
        topic_graph_path=TOPIC_GRAPH_PATH,
    )
    assert not report.valid
    assert "not found" in report.errors[0]
