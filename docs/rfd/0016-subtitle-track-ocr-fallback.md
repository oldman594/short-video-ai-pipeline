# RFD 0016: Subtitle-Track OCR Fallback

## Context

Local script validation against the `vision/` samples works when using
`auto` or `screen_text`, because those routes reach the RapidOCR hard-subtitle
path. The browser workflow can still produce poor results when a user selects
`subtitle_track` for a Douyin-style video that visually has captions but does
not contain an independent subtitle stream.

In that case the old route stopped after FFmpeg/MKVToolNix failed to find a
real subtitle track and stored fallback text. The UI then showed:

- `extraction_method`: `subtitle_track`
- `provider`: `ffmpeg-or-mkvtoolnix-fallback`

## Decision

For local media, explicit `subtitle_track` preference now plans:

1. `subtitle_track`
2. `screen_text`

This preserves independent subtitle tracks as the first choice, but if no track
exists the server attempts OCR before returning fallback text. The returned
transcript keeps the original subtitle-track warning so the UI can explain why
OCR was used.

The browser copy also distinguishes independent subtitle tracks from burned-in
visual subtitles:

- `有独立字幕轨：FFmpeg / MKVToolNix`
- `字幕烧在画面上：OCR`

## Boundaries

- `subtitle_track` still means true subtitle streams or sidecar subtitle files
  first.
- OCR is only attempted when there is a local media file.
- Link-only projects still cannot OCR unless the client uploads the saved media
  file to the server.

## Validation

Automated tests cover the explicit `subtitle_track` preference falling back to
`screen_text` when the subtitle-track extractor returns a fallback result.

Validation commands:

- `python3 -m unittest discover -s tests`
- `python3 scripts/check_line_coverage.py`
- `python3 -m compileall app tests scripts`

## Validation Results

- `python3 scripts/extract_text_local.py vision/a9cb4299954719e6941ca584178703fe.mp4 --mode subtitle_track --json`
  returned `extraction_method: screen_text` and `provider: ffmpeg-rapidocr`,
  while preserving the warning that no independent subtitle track was detected.
- `python3 -m unittest discover -s tests` passed with 28 tests.
- `python3 scripts/check_line_coverage.py` passed with 91.1% measured line
  coverage.
- `python3 -m compileall app tests scripts` passed.
