#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MAX_LINES = 400


@dataclass(frozen=True)
class Violation:
    path: str
    line_count: int
    max_lines: int


def run_git(args: list[str]) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT_DIR)


def parse_nul_paths(output: bytes) -> list[str]:
    return [part.decode("utf-8") for part in output.split(b"\0") if part]


def staged_paths() -> list[str]:
    output = run_git(["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"])
    return parse_nul_paths(output)


def tracked_paths() -> list[str]:
    output = run_git(["ls-files", "-z"])
    return parse_nul_paths(output)


def staged_file_bytes(path: str) -> bytes:
    return run_git(["show", f":{path}"])


def filesystem_file_bytes(path: str) -> bytes | None:
    file_path = ROOT_DIR / path
    if not file_path.is_file():
        return None
    return file_path.read_bytes()


def is_binary_content(content: bytes) -> bool:
    if b"\0" in content[:8192]:
        return True
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def count_text_lines(content: bytes) -> int:
    text = content.decode("utf-8")
    if not text:
        return 0
    return len(text.splitlines())


def check_contents(path: str, content: bytes | None, max_lines: int) -> Violation | None:
    if content is None or is_binary_content(content):
        return None
    line_count = count_text_lines(content)
    if line_count <= max_lines:
        return None
    return Violation(path=path, line_count=line_count, max_lines=max_lines)


def check_paths_from_filesystem(paths: list[str], max_lines: int) -> list[Violation]:
    violations = []
    for path in paths:
        violation = check_contents(path, filesystem_file_bytes(path), max_lines)
        if violation:
            violations.append(violation)
    return violations


def check_paths_from_index(paths: list[str], max_lines: int) -> list[Violation]:
    violations = []
    for path in paths:
        violation = check_contents(path, staged_file_bytes(path), max_lines)
        if violation:
            violations.append(violation)
    return violations


def print_violations(violations: list[Violation]) -> None:
    print("File line limit check failed:", file=sys.stderr)
    for violation in violations:
        print(
            f"  {violation.path}: {violation.line_count} lines "
            f"(max {violation.max_lines})",
            file=sys.stderr,
        )
    print("Split oversized text files before committing.", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Enforce max line count for committed text files.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="Check staged added/copied/modified files.")
    mode.add_argument("--all", action="store_true", help="Check all tracked files.")
    parser.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES)
    args = parser.parse_args()

    if args.max_lines < 1:
        raise SystemExit("--max-lines must be positive")

    if args.all:
        violations = check_paths_from_filesystem(tracked_paths(), args.max_lines)
    else:
        violations = check_paths_from_index(staged_paths(), args.max_lines)

    if violations:
        print_violations(violations)
        raise SystemExit(1)

    print(f"File line limit check passed (max {args.max_lines} lines).")


if __name__ == "__main__":
    main()
