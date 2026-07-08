#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import linecache
import runpy
import sys
import trace
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_THRESHOLD = 90.0
MEASURED_FILES = [
    ROOT_DIR / "app" / "providers.py",
    ROOT_DIR / "app" / "storage.py",
    ROOT_DIR / "app" / "text_extraction.py",
    ROOT_DIR / "app" / "workflow.py",
]
EXCLUDED_FUNCTIONS = {
    "extract_subtitle_with_ffmpeg",
    "has_subtitle_stream",
    "extract_speech_with_whisper",
    "extract_speech_with_whisper_cpp",
    "prepare_asr_audio",
    "detect_voice_segments",
    "audio_duration_seconds",
    "slice_audio",
    "run_whisper_cpp_chunk",
    "write_srt_file",
    "extract_screen_text_with_tesseract",
    "run_tesseract_variants",
    "extract_network_captions_with_ytdlp",
}


def executable_lines(path: Path) -> set[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: set[int] = set()
    excluded_ranges = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in EXCLUDED_FUNCTIONS:
            excluded_ranges.append((node.lineno, node.end_lineno or node.lineno))
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        if any(start <= node.lineno <= end for start, end in excluded_ranges):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.If):
            source = linecache.getline(str(path), node.lineno).strip()
            if source.startswith("if __name__ =="):
                continue
        lines.add(node.lineno)
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Run unit tests and enforce line coverage.")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT_DIR))
    tracer = trace.Trace(count=True, trace=False)
    old_argv = sys.argv[:]
    try:
        sys.argv = ["unittest", "discover", "-s", "tests"]
        try:
            tracer.runctx(
                "runpy.run_module('unittest', run_name='__main__')",
                {"runpy": runpy},
                {},
            )
        except SystemExit as exc:
            if exc.code not in (0, None):
                raise
    finally:
        sys.argv = old_argv

    results = tracer.results()
    counts = results.counts
    total_executable = 0
    total_covered = 0
    print()
    print("Line coverage:")
    for path in MEASURED_FILES:
        measured = executable_lines(path)
        covered = {
            line_number
            for (filename, line_number), count in counts.items()
            if Path(filename).resolve() == path.resolve() and count > 0
        }
        covered_measured = measured & covered
        total_executable += len(measured)
        total_covered += len(covered_measured)
        percent = 100.0 if not measured else (len(covered_measured) / len(measured)) * 100.0
        print(f"  {path.relative_to(ROOT_DIR)}: {percent:5.1f}% ({len(covered_measured)}/{len(measured)})")

        missing = sorted(measured - covered_measured)
        if missing:
            preview = ", ".join(str(line) for line in missing[:16])
            suffix = " ..." if len(missing) > 16 else ""
            print(f"    missing: {preview}{suffix}")

    total_percent = 100.0 if not total_executable else (total_covered / total_executable) * 100.0
    print(f"  TOTAL: {total_percent:5.1f}% ({total_covered}/{total_executable})")
    if total_percent < args.threshold:
        raise SystemExit(f"line coverage {total_percent:.1f}% is below required {args.threshold:.1f}%")


if __name__ == "__main__":
    main()
