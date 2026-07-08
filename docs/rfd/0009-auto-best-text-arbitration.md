# RFD 0009: Auto Best Text Arbitration

## Context

Local `auto` extraction returned combined ASR and OCR output when both succeeded. For videos with visible subtitles, RapidOCR text is usually more accurate than whisper.cpp ASR, while combined output exposes noisy homophone ASR text to downstream script analysis.

## Decision

Change local `auto` extraction to return a single best transcript:

- Independent subtitle track or sidecar subtitle remains highest priority.
- When no independent subtitle exists, run speech and screen-text OCR as candidates.
- Prefer screen-text OCR when it passes a small quality score based on provider, Chinese text volume, and line structure.
- Fall back to speech when OCR is missing or too weak.
- Return the selected candidate's original `extraction_method` and `provider`.

Explicit modes remain unchanged: `speech` returns ASR only, and `screen_text` returns OCR only.

## API or Data Model Impact

No schema changes. Local `auto` no longer returns `auto_combined` for successful ASR + OCR. It returns one selected result such as:

- `extraction_method`: `screen_text`
- `provider`: `ffmpeg-rapidocr`

## Failure Modes

- The heuristic can choose OCR if the detected visual text is readable but semantically wrong.
- Very short visible subtitles may not pass the quality threshold and may fall back to speech.
- Warnings still include attempted extractor warnings, so operators can see which paths were tried.

## Validation Plan

- Unit test that high-quality RapidOCR text wins over ASR.
- Unit test that low-quality OCR falls back to ASR.
- Local closed-loop extraction against the `vision/` sample in `auto` mode.
- Run unittest, coverage, and compile checks.

## Validation Results

- `python3 scripts/extract_text_local.py vision/61354d2054ca8878ffe02059f360e7fe.mp4 --mode auto --json` returned one selected transcript with `extraction_method: screen_text` and `provider: ffmpeg-rapidocr`.
- `python3 -m unittest discover -s tests` passed with 17 tests.
- `python3 scripts/check_line_coverage.py` passed with 90.6% measured line coverage.
- `python3 -m compileall app tests scripts` passed.
