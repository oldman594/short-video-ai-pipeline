# RFD 0012: D-ID Avatar Video Provider

## Context

The external HTTP avatar provider can connect to a wrapper service, but MVP validation can be faster when one commercial digital-human API is available directly. D-ID exposes a Talks API that creates a talking-avatar render from a public source image and a text script, then returns a result video URL after asynchronous processing.

## Decision

Add `DIDAvatarVideoProvider`:

- Enabled by `AVATAR_VIDEO_PROVIDER=did`.
- Requires `DID_API_KEY` and `DID_SOURCE_URL`.
- If `DID_SOURCE_URL` is absent, derive it from `PUBLIC_BASE_URL` plus a local `photo/` image.
- Uses D-ID Basic authorization. Raw `username:password` API keys are base64 encoded at request time; already-prefixed `Basic ...` values are passed through.
- Calls `POST /talks` with `source_url` and text `script.input`.
- Polls `GET /talks/{id}` until `result_url` is available or a terminal error/timeout occurs.
- Supports optional `DID_VOICE_ID` and `DID_VOICE_PROVIDER`.
- Keeps credentials out of repository files.

## API or Data Model Impact

No schema changes. Render jobs can now use provider:

- `d-id-avatar-video-v1`

Supported environment variables:

- `AVATAR_VIDEO_PROVIDER=did`
- `DID_API_KEY`
- `DID_SOURCE_URL`
- `PUBLIC_BASE_URL` or `APP_PUBLIC_BASE_URL`
- `DID_PHOTO_FILENAME`
- `DID_BASE_URL` defaulting to `https://api.d-id.com`
- `DID_HTTP_TIMEOUT_SECONDS`
- `DID_POLL_INTERVAL_SECONDS`
- `DID_MAX_POLLS`
- `DID_VOICE_ID`
- `DID_VOICE_PROVIDER` defaulting to `microsoft`

## Failure Modes

- Missing `DID_API_KEY` or `DID_SOURCE_URL` fails provider initialization.
- Missing `DID_SOURCE_URL` is allowed only when `PUBLIC_BASE_URL` points to a public server and an allowed local `photo/` image exists.
- `PUBLIC_BASE_URL` values pointing to localhost will not work for D-ID cloud requests even though the local URL route exists.
- D-ID HTTP, network, and invalid JSON responses fail the render job with a mapped error.
- Create responses without `id` or `result_url` fail immediately.
- Polling terminal statuses such as `error`, `failed`, or `rejected` fail the render job.
- Polling timeout fails the render job.

## Validation Plan

- Unit test D-ID create + poll success using fake responses.
- Unit test Basic auth formatting.
- Unit test local `photo/` URL derivation.
- Unit test D-ID failure status.
- Unit test provider selection from environment variables.
- Run unittest, coverage, and compile checks.

## Validation Results

- `python3 -m unittest discover -s tests` passed with 24 tests after local photo source support.
- `python3 scripts/check_line_coverage.py` passed with 91.2% measured line coverage after local photo source support.
- `python3 -m compileall app tests scripts` passed.
- Live D-ID render validation was intentionally not run to avoid spending credits and because `DID_SOURCE_URL` was not provided.
