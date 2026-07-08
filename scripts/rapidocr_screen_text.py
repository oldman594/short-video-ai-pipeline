#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RapidOCR over extracted subtitle frames.")
    parser.add_argument("images", nargs="+", help="Frame image paths.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--min-confidence", type=float, default=0.55)
    args = parser.parse_args()

    from rapidocr_onnxruntime import RapidOCR

    ocr = RapidOCR()
    items = []
    for image in args.images:
        path = Path(image)
        if not path.is_file():
            continue
        result, _elapsed = ocr(str(path))
        for row in result or []:
            if len(row) < 3:
                continue
            box, text, confidence = row[0], str(row[1]).strip(), float(row[2])
            if text and confidence >= args.min_confidence:
                items.append(
                    {
                        "image": path.name,
                        "text": text,
                        "confidence": confidence,
                        "box": box,
                    }
                )

    if args.json:
        print(json.dumps({"items": items}, ensure_ascii=False))
        return
    for item in items:
        print(item["text"])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise
