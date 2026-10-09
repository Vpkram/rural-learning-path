"""Read per-subject video metadata and build safe YouTube search links."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse


def topic_video_entries(
    pack_directory: str | Path,
    topic: str,
    *,
    language: str = "en",
) -> dict[str, object] | None:
    """Return a language-preferred topic entry, or None when none is defined."""
    path = Path(pack_directory) / "videos.json"
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read video catalog {path}: {exc}") from exc
    entries = catalog.get("videos") if isinstance(catalog, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"Video catalog {path} must contain a videos list.")
    matching = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("topic") == topic
        and entry.get("language") == language
    ]
    if not matching and language != "en":
        matching = [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and entry.get("topic") == topic
            and entry.get("language") == "en"
        ]
    return matching[0] if matching else None


def verified_video_url(value: str) -> bool:
    """Accept direct video media links and YouTube watch/embed links."""
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    host = parsed.hostname.casefold()
    if host == "youtu.be":
        return len(parsed.path.strip("/").split("/")) == 1
    if host == "youtube.com" or host.endswith(".youtube.com"):
        path_parts = [part for part in parsed.path.split("/") if part]
        if parsed.path == "/watch":
            return bool(parse_qs(parsed.query).get("v", [""])[0])
        return len(path_parts) >= 2 and path_parts[0] in {"embed", "shorts", "live"}
    return Path(parsed.path).suffix.casefold() in {".mp4", ".webm", ".mov", ".m3u8"}


def video_render_action(entry: dict[str, object] | None) -> tuple[str, str | None]:
    """Return a playable URL only for an explicitly verified media source."""
    if entry is None or entry.get("verified") is not True:
        return "search", None
    url = entry.get("url")
    if not isinstance(url, str) or not verified_video_url(url):
        return "search", None
    return "video", url


def search_videos_url(
    class_name: str,
    subject: str,
    topic: str,
    *,
    stream: str = "",
) -> str:
    """Build a YouTube search URL from the selected class/stream/subject/topic."""
    query = " ".join(part.strip() for part in (class_name, stream, subject, topic) if part.strip())
    return "https://www.youtube.com/results?" + urlencode({"search_query": query})
