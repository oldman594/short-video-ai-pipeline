from __future__ import annotations

import unittest

from scripts import check_file_line_limits


class FileLineLimitTests(unittest.TestCase):
    def test_oversized_text_content_reports_violation(self) -> None:
        # Objective: prove the guard fails a staged text file whose committed
        # content exceeds the repository line budget. Construction method:
        # 1. Build synthetic UTF-8 content with five newline-separated lines.
        # 2. Run the same content checker used by the pre-commit script.
        # 3. Set the max line budget below the generated line count. Input data:
        # a fake Python path and a five-line ASCII byte string. Expected
        # behavior: the checker returns a violation with the original path,
        # observed line count, and configured maximum so the commit output can
        # tell the author exactly which file needs splitting.
        content = b"one\ntwo\nthree\nfour\nfive\n"

        violation = check_file_line_limits.check_contents("app/example.py", content, max_lines=4)

        self.assertIsNotNone(violation)
        assert violation is not None
        self.assertEqual("app/example.py", violation.path)
        self.assertEqual(5, violation.line_count)
        self.assertEqual(4, violation.max_lines)

    def test_binary_content_is_skipped(self) -> None:
        # Objective: confirm media files and other binary artifacts are outside
        # the text-file line rule. Construction method:
        # 1. Create bytes containing a NUL marker like common binary formats.
        # 2. Pass the bytes through the shared checker with a very small limit.
        # 3. Assert no violation is produced. Input data: a fake MP4 path and
        # binary-looking bytes. Expected behavior: the checker returns None so
        # existing or newly staged video assets are not counted as long text.
        content = b"\x00\x00\x00 ftypmp42\n" * 10

        violation = check_file_line_limits.check_contents("vision/example.mp4", content, max_lines=1)

        self.assertIsNone(violation)

    def test_multibyte_utf8_text_counts_lines(self) -> None:
        # Objective: ensure Chinese documentation and prompts are treated as
        # normal text instead of being skipped as binary content. Construction
        # method:
        # 1. Encode three Chinese lines as UTF-8 bytes.
        # 2. Use the shared checker with a maximum that allows all lines.
        # 3. Verify no violation is returned. Input data: a Markdown path and
        # three short Chinese lines. Expected behavior: UTF-8 content decodes
        # successfully and is counted against the configured limit.
        content = "第一行\n第二行\n第三行\n".encode("utf-8")

        violation = check_file_line_limits.check_contents("docs/example.md", content, max_lines=3)

        self.assertIsNone(violation)


if __name__ == "__main__":
    unittest.main()
