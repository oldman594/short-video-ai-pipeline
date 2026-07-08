# RFD 0003: Link Projects With Server-Side Media Extraction

## Context

Link-only projects cannot perform speech recognition or OCR because the server has no local media file. The previous auto strategy tried network captions for link projects first, which correctly preserved the compliance boundary, but for Douyin links it produced a fallback transcript unless the user separately uploaded media.

The desired user flow is:

1. User provides a source link for attribution and project context.
2. User also provides the actual video file when direct platform access is unavailable or not allowed.
3. The server receives the file and performs text extraction centrally.
4. The client receives the extracted transcript, method, provider, and warnings through project status responses.

## Decision

Allow `POST /api/projects` to include an optional uploaded file for `source_type=link`.

For auto extraction:

- If a local media file is available, the router tries local extraction first: subtitle track, then speech.
- If no local media file is available, link projects try network captions, then speech fallback.

Add a server-side tool status endpoint:

- `GET /api/system/text-extraction-tools`

The endpoint reports whether FFmpeg, MKVToolNix, Whisper, Tesseract, and yt-dlp are available on the server and gives local install hints.

The browser does not attempt to download cross-origin videos. The UI labels link-attached files as user-provided local media.

## API or Data Model Impact

`POST /api/projects` now accepts `file` for both:

- `source_type=upload`: file is required.
- `source_type=link`: file is optional but recommended for platforms where network extraction is unavailable.

No database schema change is required because projects already store both `source_url` and `source_file_path`.

## Failure Modes

- Link project without attached media still falls back when network captions are disabled or unavailable.
- Browser-side automatic cross-origin video download is intentionally not implemented.
- Missing server tools are reported in transcript warnings and in the tool status endpoint.
- Tool installation remains an operator action, not an unauthenticated web action.

## Validation Plan

- Unit test auto routing prefers local media for link projects when a file path exists.
- API test link project accepts an optional attached file.
- Run unittest and compile checks.
- Restart local server and smoke test link project with optional file payload.

## Validation Results

- `python3 -m unittest discover -s tests` passed with 6 tests.
- `python3 -m compileall app tests` passed.
- Router tests verify auto mode prefers local media for link projects when `source_file_path` is present.
- API tests verify link projects accept optional uploaded media and invalid extraction preferences still return HTTP 400.
