import json

from core.subject_videos import (
    search_videos_url,
    topic_video_entries,
    video_render_action,
)
from scripts.check_videos import check_videos


def test_video_rendering_uses_only_verified_playable_urls():
    assert video_render_action(
        {
            "url": "https://www.youtube.com/watch?v=abc123",
            "verified": True,
        }
    ) == ("video", "https://www.youtube.com/watch?v=abc123")
    assert video_render_action(
        {
            "url": "https://www.youtube.com/results?search_query=math",
            "verified": False,
        }
    ) == ("search", None)
    assert video_render_action(
        {
            "url": "https://www.youtube.com/results?search_query=math",
            "verified": True,
        }
    ) == ("search", None)
    assert video_render_action({"url": None, "verified": False}) == ("search", None)
    assert video_render_action(
        {"url": "https://example.org/page", "verified": True}
    ) == ("search", None)


def test_topic_video_lookup_and_search_query_include_context(tmp_path):
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "videos.json").write_text(
        json.dumps(
            {
                "videos": [
                    {
                        "topic": "Fractions",
                        "title": None,
                        "source": None,
                        "url": None,
                        "duration_min": None,
                        "language": "en",
                        "verified": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    entry = topic_video_entries(pack, "Fractions")
    assert entry is not None and entry["verified"] is False
    assert topic_video_entries(pack, "Decimals") is None
    url = search_videos_url("Class 8", "Mathematics", "Fractions")
    assert "Class+8+Mathematics+Fractions" in url
    assert video_render_action(entry)[0] == "search"


def test_video_audit_reports_missing_verified_topics_and_broken_urls(
    tmp_path,
    monkeypatch,
):
    pack = tmp_path / "Class 1" / "mathematics"
    pack.mkdir(parents=True)
    (pack / "topics.json").write_text(
        json.dumps(
            {
                "subject": {
                    "class_level": "Class 1",
                    "name": "Mathematics",
                    "stream": "",
                },
                "topics": [{"name": "Counting"}, {"name": "Shapes"}],
            }
        ),
        encoding="utf-8",
    )
    (pack / "videos.json").write_text(
        json.dumps(
            {
                "videos": [
                    {
                        "topic": "Counting",
                        "url": "https://example.org/counting.mp4",
                        "verified": True,
                    },
                    {
                        "topic": "Shapes",
                        "url": "https://example.org/shapes",
                        "verified": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.check_videos._check_url",
        lambda url, timeout: "unreachable" if url.endswith("/shapes") else None,
    )

    missing, broken = check_videos(tmp_path)

    assert missing == ["Class 1 /  / Mathematics / Shapes"]
    assert broken == [
        "Class 1 / Mathematics / Shapes: https://example.org/shapes (unreachable)"
    ]
