# RFD 0008: RapidOCR for Burned-In Subtitles

## Context

The local `vision/61354d2054ca8878ffe02059f360e7fe.mp4` sample has visible burned-in subtitles but no independent subtitle stream. `speech` mode uses ASR and produced many homophone errors. The previous `screen_text` path used Tesseract only, which performed poorly on bold outlined short-video subtitles.

## Decision

Add an optional RapidOCR path for `screen_text`:

- Extract subtitle-region frames with FFmpeg.
- Run OCR through `scripts/rapidocr_screen_text.py` from an isolated `.venv-ocr`.
- Prefer RapidOCR output in `ScreenTextExtractor`.
- Fall back to Tesseract when RapidOCR is missing, empty, or fails.
- Keep `speech` as ASR-only; users should run `screen_text` to evaluate visual subtitle OCR.

`scripts/bootstrap_ocr_local.sh` creates `.venv-ocr` and installs `rapidocr_onnxruntime`.

## API or Data Model Impact

No schema changes. Successful hard-subtitle OCR now reports:

- `extraction_method`: `screen_text`
- `provider`: `ffmpeg-rapidocr`

## Failure Modes

- RapidOCR is optional; if `.venv-ocr` is missing, the service records a warning and tries Tesseract.
- FFmpeg crop parameters target common bottom-center short-video subtitles and may need tuning for unusual layouts.
- OCR still may misread stylized text, but it is materially better than ASR for visible subtitles.

## Validation Plan

- Unit tests for RapidOCR JSON parsing and `ScreenTextExtractor` routing.
- Local closed-loop extraction against the `vision/` sample in `screen_text` and `auto` modes.
- Run unittest, coverage, and compile checks.

## Validation Results

- `python3 scripts/extract_text_local.py vision/61354d2054ca8878ffe02059f360e7fe.mp4 --mode screen_text --json` returned `provider: ffmpeg-rapidocr` with 8 subtitle lines.
- Later RFD 0009 changes local `auto` from combined output to best-result arbitration.
- `python3 -m unittest discover -s tests` passed with 16 tests.
- `python3 scripts/check_line_coverage.py` passed with 90.9% measured line coverage.
- `python3 -m compileall app tests scripts` passed.
