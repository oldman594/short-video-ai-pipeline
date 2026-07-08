# RFD 0002: Text Extraction Routing

## Context

The current MVP uses one mock ASR provider for every source. That keeps the pipeline runnable, but it does not match the real extraction paths needed to obtain text from different video conditions:

- Videos with subtitle tracks should prefer subtitle extraction with FFmpeg or MKVToolNix.
- Videos with only speech should use ASR such as Whisper or a cloud speech provider.
- Videos with text burned into the frame should use OCR such as PaddleOCR, Tesseract, or VideoSubFinder.
- Network videos should first try available captions, then fall back to speech recognition.

The local environment currently has none of these external tools installed, so the MVP must keep graceful fallback behavior.

## Decision

Introduce a text extraction router with explicit extraction modes:

- `auto`
- `subtitle_track`
- `speech`
- `screen_text`
- `network_captions`

The router chooses a strategy from user preference and source type:

- `network_captions` for link projects when the user selects network captions.
- `subtitle_track` for upload projects when the user selects subtitle track.
- `screen_text` for upload projects when the user selects screen text.
- `speech` for speech-only projects.
- `auto` first tries network captions for links, then subtitle tracks for uploads, then speech.

Each extractor returns the same transcript shape:

- `raw_text`
- `segments`
- `language`
- `provider`
- `extraction_method`
- `warnings`

Real external tools are optional. Missing tools produce warnings and deterministic fallback text so the MVP still supports the rest of the content workflow.

## API or Data Model Impact

Projects add an `extraction_preference` field.

Transcripts add:

- `extraction_method`
- `warnings_json`

`POST /api/projects` accepts:

```json
{
  "extraction_preference": "auto"
}
```

The project detail response includes the selected preference and transcript extraction metadata.

## Failure Modes

- Unknown extraction preference returns `400`.
- Missing local tools do not fail the project; they create warnings and use mock fallback text.
- Network caption extraction with `yt-dlp` is disabled unless `ALLOW_NETWORK_MEDIA_FETCH=1`.
- Douyin URLs are not fetched by the MVP even when the network fetch flag is enabled.
- OCR/ASR tool failures return warnings and fall back to deterministic transcript text.

## Validation Plan

- Unit test router strategy selection for explicit preferences and auto mode.
- Unit test workflow stores extraction method and warnings.
- Unit test invalid API extraction preference is rejected.
- Run unittest and compile checks.

## Validation Results

- `python3 -m unittest discover -s tests` passed with 4 tests.
- `python3 -m compileall app tests` passed.
- Router tests cover explicit subtitle-track extraction and link auto fallback from network captions to speech.
- Workflow tests verify transcript extraction metadata and warnings are stored with generated review artifacts.
- API tests verify unknown extraction preferences return HTTP 400.

## Open Questions

- Which ASR provider should be wired first: local Whisper, OpenAI/Whisper API, or a Chinese cloud provider.
- Whether OCR should sample frames in-app or delegate entirely to VideoSubFinder/PaddleOCR tooling.
- Whether network caption extraction should remain an opt-in advanced feature or be hidden until a supported official integration exists.
