# RFD 0011: External Avatar Video Provider

## Context

The current render workflow creates a mock text artifact after script approval. The next product step is to connect a real digital-human video service while keeping provider boundaries and the human review gate intact.

Open-source projects worth learning from include SadTalker, Wav2Lip, MuseTalk, LivePortrait, and Linly-Talker. They commonly expose or can be wrapped behind an audio/text-driven talking-head render service. Commercial avatar APIs can be wrapped behind the same contract.

## Decision

Add an `ExternalHttpAvatarVideoProvider`:

- Enabled by `AVATAR_VIDEO_PROVIDER=external-http`.
- Requires `AVATAR_VIDEO_ENDPOINT`.
- Optionally sends `Authorization: Bearer <AVATAR_VIDEO_API_KEY>`.
- Sends the approved script, title options, desired output format, and a development contract marker.
- Accepts either a remote `output_video_url` or local `output_base64` video data.
- Stores base64 video output under `data/outputs/`.
- Keeps `MockAvatarVideoProvider` as the default when external provider configuration is absent.

The UI labels the feature as development-stage video generation.

## API or Data Model Impact

No schema changes. Existing render jobs already store:

- `provider`
- `status`
- `output_video_url`
- `error_message`

External render jobs use provider:

- `external-http-avatar-video-dev`

Expected external service request shape:

```json
{
  "script_id": "script uuid",
  "script_text": "approved script",
  "title": "first title option",
  "title_options": ["title 1"],
  "output_format": "mp4",
  "provider_contract": "short-video-ai-pipeline.avatar.render.v1",
  "development_status": "in_development"
}
```

Expected response shape:

```json
{"output_video_url": "https://cdn.example/video.mp4"}
```

or:

```json
{"filename": "render.mp4", "output_base64": "..."}
```

## Failure Modes

- Missing `AVATAR_VIDEO_ENDPOINT` fails provider initialization when external mode is selected.
- HTTP failures and malformed JSON fail the render job with a mapped error.
- Responses without `output_video_url` or `output_base64` fail the render job.
- Base64 video decoding errors fail the render job.
- Live external render integration is not run in unit tests.

## Validation Plan

- Unit tests for external provider URL response.
- Unit tests for base64 response persistence.
- Unit tests for HTTP, network, invalid JSON, missing output, invalid base64, and missing config errors.
- Workflow/API tests continue to cover approval gate and render job transitions.
- Run unittest, coverage, and compile checks.

## Validation Results

- `python3 -m unittest discover -s tests` passed with 21 tests.
- `python3 scripts/check_line_coverage.py` passed with 92.1% measured line coverage.
- `python3 -m compileall app tests scripts` passed.
- Live external avatar render validation was intentionally not run because no provider endpoint or credentials are configured.
