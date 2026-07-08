# RFD 0006: Auto Combines Speech and Burned-In Subtitle OCR

## Context

The `vision/` test video visually contains subtitles, but FFprobe reports no subtitle stream. This means the subtitles are burned into the video frames rather than stored as an embedded subtitle track.

The previous auto mode stopped at the first successful non-fallback extractor. When ASR succeeded, OCR was skipped, so users could reasonably think visible subtitles were ignored.

## Decision

For local media in `auto` mode:

- Try subtitle-track extraction first.
- If a real subtitle track or sidecar subtitle is found, return it.
- Otherwise run speech extraction and screen-text OCR.
- If both speech and OCR produce real text, return a combined transcript.
- Clarify subtitle-track warnings to distinguish embedded subtitle tracks from burned-in visual subtitles.

Explicit modes remain unchanged:

- `speech` returns only ASR.
- `screen_text` returns only OCR.
- `subtitle_track` returns only subtitle-track/sidecar extraction.

## API or Data Model Impact

No schema or endpoint changes. Combined auto extraction uses:

- `extraction_method`: `auto_combined`
- `provider`: joined provider names such as `whisper.cpp+ffmpeg-tesseract`

## Failure Modes

- OCR quality can still be poor for stylized video subtitles.
- Tiny whisper.cpp model accuracy is limited.
- If ASR succeeds and OCR fails, auto returns ASR with OCR warnings.

## Validation Plan

- Unit test auto combines ASR and OCR when subtitle-track extraction falls back.
- Unit test auto returns subtitle-track result immediately when subtitle-track succeeds.
- Run local extraction for the `vision/` video in auto mode.
- Run unittest, coverage check, and compile checks.

## Validation Results

- `python3 scripts/extract_text_local.py vision/61354d2054ca8878ffe02059f360e7fe.mp4 --mode auto` returned `method: auto_combined` and `provider: whisper.cpp+ffmpeg-tesseract`.
- The `vision/` video still has no independent subtitle stream according to FFprobe; its visible subtitles are burned into the frames.
- `python3 -m unittest discover -s tests` passed with 15 tests.
- `python3 scripts/check_line_coverage.py` passed with 91.1% measured line coverage.
- `python3 -m compileall app tests scripts` passed.
