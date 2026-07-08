# RFD 0001: Standard Library MVP

## Context

The product documents define an MVP that accepts a source link or uploaded video, creates a project, extracts or obtains a transcript, analyzes the content, generates original scripts, allows human review, and produces a draft artifact for export.

The local environment has Python 3.14 available, but no `just`, `ffmpeg`, FastAPI, Uvicorn, Pydantic, SQLAlchemy, or pytest packages installed. The MVP should run without requiring API credentials, paid third-party calls, or platform-specific scraping.

## Decision

Build the first MVP as a dependency-free Python application:

- Use `http.server` for the API and static UI.
- Use `sqlite3` for local persistence.
- Use JSON-over-HTTP endpoints.
- Use a background thread executor for asynchronous project processing.
- Use provider interfaces with mock implementations for ASR, LLM analysis, script generation, and avatar video rendering.
- Store uploaded source files and render draft artifacts under `data/`.

This keeps the workflow runnable immediately while preserving the architecture boundary needed to replace the web layer with FastAPI, the worker with Celery, and the mock providers with real ASR/LLM/avatar services later.

## API or Data Model Impact

The MVP implements these API endpoints:

- `GET /`
- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{project_id}`
- `PATCH /api/projects/{project_id}/transcript`
- `PATCH /api/scripts/{script_id}`
- `POST /api/scripts/{script_id}/approve`
- `POST /api/scripts/{script_id}/render`
- `GET /api/render-jobs/{render_job_id}`
- `GET /outputs/{filename}`

SQLite tables:

- `projects`
- `transcripts`
- `analyses`
- `scripts`
- `render_jobs`

Uploads use base64 JSON payloads in the browser to avoid adding multipart parsing dependencies.

## Failure Modes

- Invalid JSON returns `400`.
- Missing records return `404`.
- Invalid state transitions, such as rendering an unapproved script, return `409`.
- Background project processing failures set the project status to `failed` and store an error message.
- Render failures set the render job status to `failed` and store an error message.
- Uploaded files are stored locally only; large uploads are not optimized in this MVP.

## Validation Plan

- Unit tests for repository persistence and the project workflow.
- Unit tests for the required review gate before rendering.
- Manual API smoke test against the local server.
- Manual UI smoke test in the browser after the server starts.

## Validation Results

- `python3 -m unittest discover -s tests` passed.
- `python3 -m compileall app tests` passed.
- Manual API smoke test for `GET /` passed with `200 text/html`.
- Manual API smoke test for `POST /api/projects` passed and produced a `ready_for_review` project with one transcript and three scripts.
- Manual API smoke test for script approval and render passed and produced a succeeded render job with a downloadable `/outputs/render-*.txt` artifact.
- Browser UI smoke testing remains manual for the user, with the local server running at `http://127.0.0.1:8000`.

## Open Questions

- Which real ASR provider should be connected first.
- Which LLM provider and prompt format should be productionized first.
- Which avatar video provider should be used for the first real render integration.
- Whether the next iteration should migrate the web layer to FastAPI before connecting external providers.
