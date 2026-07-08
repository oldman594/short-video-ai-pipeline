# RFD 0013: Local Avatar Photo Source for D-ID

## Context

The user prepared an avatar image under `photo/`. D-ID requires `source_url` to be reachable by D-ID's cloud service, so a local filesystem path cannot be used directly. For the MVP, we need a small bridge that can expose a prepared avatar image as a URL when the app is deployed behind a public base URL.

Future UI upload can reuse the same storage and route pattern.

## Decision

Add local avatar photo support:

- Create `PHOTO_DIR` at repository-level `photo/`.
- Serve allowed image files through read-only `/photos/<filename>`.
- Allow D-ID provider to derive `source_url` from `PUBLIC_BASE_URL` plus `/photos/<filename>` when `DID_SOURCE_URL` is not set.
- Support `DID_PHOTO_FILENAME`; otherwise use the first allowed image in `photo/`.
- Ignore `photo/*` in git so user avatar assets are not committed accidentally.

Allowed photo suffixes:

- `.jpg`
- `.jpeg`
- `.png`
- `.webp`

## API or Data Model Impact

No schema changes. New read-only route:

```text
GET /photos/{filename}
```

New environment variables:

- `PUBLIC_BASE_URL`
- `APP_PUBLIC_BASE_URL`
- `DID_PHOTO_FILENAME`

## Failure Modes

- D-ID cannot access localhost URLs; `PUBLIC_BASE_URL` must be public.
- Missing public base URL and missing `DID_SOURCE_URL` fails D-ID provider initialization.
- Unsupported photo suffixes return 404 from `/photos/...`.
- The app only serves files by basename to avoid path traversal.
- User must have rights/consent to use the uploaded avatar photo.

## Validation Plan

- Unit test `/photos/...` serves allowed image files and rejects disallowed files.
- Unit test D-ID source URL derivation from `photo/`.
- Run unittest, coverage, and compile checks.

## Validation Results

- `python3 -m unittest discover -s tests` passed with 24 tests.
- `python3 scripts/check_line_coverage.py` passed with 91.2% measured line coverage.
- `python3 -m compileall app tests scripts` passed.
- Live D-ID validation was intentionally not run because a public `PUBLIC_BASE_URL` was not provided.
