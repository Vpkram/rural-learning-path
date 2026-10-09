"""Migrate the legacy CSV rows into per-subject video catalogs.

Existing CSV URLs are marked unverified: they are search links and must never
be embedded as video players without owner review.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from db.seed import SUBJECT_PACKS_DIRECTORY


def migrate_videos(
    packs_directory: str | Path = SUBJECT_PACKS_DIRECTORY,
    legacy_csv: str | Path = Path(__file__).resolve().parent.parent / "data" / "videos.csv",
) -> int:
    """Create a videos.json in every discovered subject directory."""
    root = Path(packs_directory)
    legacy_path = Path(legacy_csv)
    legacy_rows: dict[tuple[str, str, str], dict[str, str]] = {}
    if legacy_path.is_file():
        with legacy_path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                legacy_rows[
                    (row["subject"].strip(), row["topic"].strip(), row["language"].strip())
                ] = {key: (value or "").strip() for key, value in row.items()}

    written = 0
    for topics_path in sorted(
        set(root.glob("*/*/topics.json")) | set(root.glob("*/*/*/topics.json"))
    ):
        catalog = json.loads(topics_path.read_text(encoding="utf-8"))
        subject = catalog["subject"]
        subject_key = subject["key"]
        entries = []
        for topic in catalog["topics"]:
            for language in ("en", "te"):
                legacy = legacy_rows.get((subject_key, topic["name"], language))
                try:
                    duration = int(legacy["duration_min"]) if legacy and legacy["duration_min"] else None
                except ValueError:
                    duration = None
                entries.append(
                    {
                        "topic": topic["name"],
                        "title": legacy.get("title") if legacy else None,
                        "source": "Legacy CSV (unverified)" if legacy else None,
                        "url": legacy.get("url") if legacy else None,
                        "duration_min": duration,
                        "language": language,
                        "verified": False,
                    }
                )
        target = topics_path.parent / "videos.json"
        target.write_text(
            json.dumps({"videos": entries}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written += len(entries)
    return written


if __name__ == "__main__":
    print(f"Migrated {migrate_videos()} unverified video entries.")
