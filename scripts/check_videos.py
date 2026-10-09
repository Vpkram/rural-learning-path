"""List subject topics without verified videos and links that fail to load."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if __package__ in (None, ""):
    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from db.seed import SUBJECT_PACKS_DIRECTORY


def _check_url(url: str, timeout: float) -> str | None:
    try:
        request = Request(
            url,
            headers={"User-Agent": "RuralLearningPath-video-checker/1.0"},
            method="GET",
        )
        with urlopen(request, timeout=timeout) as response:
            if response.status >= 400:
                return f"HTTP {response.status}"
            response.read(1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return str(exc)
    return None


def check_videos(
    packs_directory: str | Path = SUBJECT_PACKS_DIRECTORY,
    *,
    timeout: float = 8.0,
) -> tuple[list[str], list[str]]:
    """Return missing verified topic videos and unreachable supplied URLs."""
    root = Path(packs_directory)
    missing: list[str] = []
    broken: list[str] = []
    topic_files = set(root.glob("*/*/topics.json")) | set(root.glob("*/*/*/topics.json"))
    for topics_path in sorted(topic_files):
        subject = json.loads(topics_path.read_text(encoding="utf-8"))["subject"]
        video_path = topics_path.parent / "videos.json"
        video_data = (
            json.loads(video_path.read_text(encoding="utf-8"))
            if video_path.is_file()
            else {"videos": []}
        )
        entries = video_data.get("videos", [])
        for topic in json.loads(topics_path.read_text(encoding="utf-8"))["topics"]:
            verified = [
                entry
                for entry in entries
                if entry.get("topic") == topic["name"]
                and entry.get("verified") is True
                and isinstance(entry.get("url"), str)
                and entry["url"].strip()
            ]
            if not verified:
                missing.append(
                    f"{subject['class_level']} / {subject.get('stream', '')} / "
                    f"{subject['name']} / {topic['name']}"
                )
        for entry in entries:
            url = entry.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            error = _check_url(url, timeout)
            if error:
                broken.append(
                    f"{subject['class_level']} / {subject['name']} / "
                    f"{entry.get('topic')}: {url} ({error})"
                )
    return missing, broken


def main() -> int:
    missing, broken = check_videos()
    print("Topics without verified video links:")
    for item in missing:
        print(f"  - {item}")
    print("\nVideo URLs that failed to load:")
    for item in broken:
        print(f"  - {item}")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
