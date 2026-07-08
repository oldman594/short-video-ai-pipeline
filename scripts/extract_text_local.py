#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.providers import SourceInput
from app.text_extraction import TextExtractionRouter


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract text from a local media file.")
    parser.add_argument("media", help="Path to a local video/audio file.")
    parser.add_argument(
        "--mode",
        default="auto",
        choices=["auto", "subtitle_track", "speech", "screen_text", "network_captions"],
        help="Extraction preference.",
    )
    parser.add_argument("--title", default="local extraction", help="Project title context.")
    parser.add_argument("--json", action="store_true", help="Print the full transcript JSON.")
    args = parser.parse_args()

    media = Path(args.media)
    if not media.is_file():
        raise SystemExit(f"media file not found: {media}")

    result = TextExtractionRouter().extract(
        SourceInput(
            source_type="upload",
            title=args.title,
            platform="local",
            source_url=None,
            source_file_path=str(media),
            notes="",
        ),
        args.mode,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"method: {result['extraction_method']}")
    print(f"provider: {result['provider']}")
    print("warnings:")
    for warning in result["warnings"]:
        print(f"- {warning}")
    print()
    print(result["raw_text"])


if __name__ == "__main__":
    main()
