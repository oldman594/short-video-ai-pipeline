# RFD 0015: Long-Video Screen Text Sampling

## Context

The local `vision/a9cb4299954719e6941ca584178703fe.mp4` sample is about 384
seconds long and contains burned-in subtitles rather than an independent
subtitle stream. The existing OCR path extracted a fixed number of frames at
`fps=1` from the beginning of the video:

- RapidOCR: first 45 frames
- Tesseract: first 30 frames

For long videos this only covers the opening seconds, so downstream transcript
analysis receives an incomplete text sample even when visible subtitles are
present throughout the video.

## Decision

Change screen-text OCR frame extraction from fixed opening sampling to
duration-aware whole-video sampling.

- Detect media duration with FFprobe when available.
- Keep `fps=1` for short videos.
- For long videos, use `max_frames / duration` as the FPS so frames are spread
  across the whole media.
- Keep a hard frame cap to avoid unbounded OCR cost.
- Use a lower-center subtitle crop so bottom-positioned short-video captions are
  included while right-side platform watermarks are mostly excluded.
- Filter obvious platform UI lines such as watermark account IDs and search-page
  prompts from OCR output.

Default caps:

- RapidOCR: 90 frames
- Tesseract: 45 frames

## Boundaries

- This remains OCR for burned-in text, not true subtitle-track extraction.
- Uniform sampling can still miss very fast subtitle changes.
- Large decorative title text can appear in OCR results when it is inside the
  sampled subtitle region and passes text filters.
- Videos with unusual subtitle placement may still need a future layout detector
  or a VideoSubFinder-style subtitle-region step.

## Validation

Automated tests cover:

- short-video sampling remains at 1 fps
- long-video sampling lowers fps to distribute frames across the full duration
- invalid FFprobe output falls back safely

Manual validation target:

- `python3 scripts/extract_text_local.py vision/a9cb4299954719e6941ca584178703fe.mp4 --mode screen_text --json`
- `python3 scripts/extract_text_local.py vision/a9cb4299954719e6941ca584178703fe.mp4 --mode auto --json`

## Validation Results

- `screen_text` on `vision/a9cb4299954719e6941ca584178703fe.mp4` returned
  `provider: ffmpeg-rapidocr` with text sampled across the video, including
  lines such as `第一个误解`, `第二个误解`, `科学从没说过这话`, and `再到原来如此`.
- `auto` on the same video selected `extraction_method: screen_text` and
  `provider: ffmpeg-rapidocr`.
- `screen_text` on the earlier short `vision/61354d2054ca8878ffe02059f360e7fe.mp4`
  sample still returned the main subtitle lines, with watermark fragments
  filtered.
- `python3 -m unittest discover -s tests` passed with 27 tests.
- `python3 scripts/check_line_coverage.py` passed with 91.2% measured line
  coverage.
- `python3 -m compileall app tests scripts` passed.
