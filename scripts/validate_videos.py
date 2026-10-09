"""Validate video CSV coverage against the subject question bank and topic graph."""

from __future__ import annotations

import argparse
from pathlib import Path

from core.video_recommender import DEFAULT_VIDEO_CSV, validate_video_csv
from db.seed import QUESTION_BANK_PATH, TOPIC_GRAPH_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description="Check video links and topic/language coverage.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_VIDEO_CSV)
    parser.add_argument("--bank", type=Path, default=QUESTION_BANK_PATH)
    parser.add_argument("--graph", type=Path, default=TOPIC_GRAPH_PATH)
    args = parser.parse_args()

    report = validate_video_csv(
        args.csv,
        question_bank_path=args.bank,
        topic_graph_path=args.graph,
    )
    if report.valid:
        print("Video CSV is valid.")
    for error in report.errors:
        print(f"ERROR: {error}")
    for warning in report.warnings:
        print(f"WARNING: {warning}")
    if report.missing_topics:
        print(f"Missing topics: {', '.join(report.missing_topics)}")
    if report.missing_languages:
        print(f"Missing language coverage: {', '.join(report.missing_languages)}")
    if report.invalid_links:
        print(f"Invalid links: {', '.join(report.invalid_links)}")
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
