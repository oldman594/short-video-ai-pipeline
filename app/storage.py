from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


JsonObject = dict[str, Any]


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Repository:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  source_type TEXT NOT NULL,
                  source_url TEXT,
                  source_file_path TEXT,
                  platform TEXT,
                  title TEXT,
                  notes TEXT,
                  extraction_preference TEXT NOT NULL DEFAULT 'auto',
                  status TEXT NOT NULL,
                  error_message TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS transcripts (
                  id TEXT PRIMARY KEY,
                  project_id TEXT NOT NULL REFERENCES projects(id),
                  raw_text TEXT NOT NULL,
                  segments_json TEXT NOT NULL,
                  language TEXT,
                  asr_provider TEXT,
                  extraction_method TEXT NOT NULL DEFAULT 'speech',
                  warnings_json TEXT NOT NULL DEFAULT '[]',
                  subtitle_file_url TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS analyses (
                  id TEXT PRIMARY KEY,
                  project_id TEXT NOT NULL REFERENCES projects(id),
                  topic TEXT,
                  audience TEXT,
                  category TEXT,
                  hook TEXT,
                  structure_json TEXT NOT NULL,
                  key_points_json TEXT NOT NULL,
                  risks_json TEXT NOT NULL,
                  provider TEXT,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scripts (
                  id TEXT PRIMARY KEY,
                  project_id TEXT NOT NULL REFERENCES projects(id),
                  version INTEGER NOT NULL,
                  script_text TEXT NOT NULL,
                  storyboard_json TEXT NOT NULL,
                  title_options_json TEXT NOT NULL,
                  cover_text_options_json TEXT NOT NULL,
                  tags_json TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS render_jobs (
                  id TEXT PRIMARY KEY,
                  project_id TEXT NOT NULL REFERENCES projects(id),
                  script_id TEXT NOT NULL REFERENCES scripts(id),
                  provider TEXT NOT NULL,
                  status TEXT NOT NULL,
                  output_video_url TEXT,
                  error_message TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "projects", "extraction_preference", "TEXT NOT NULL DEFAULT 'auto'")
            self._ensure_column(conn, "transcripts", "extraction_method", "TEXT NOT NULL DEFAULT 'speech'")
            self._ensure_column(conn, "transcripts", "warnings_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "transcripts", "subtitle_file_url", "TEXT")

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        existing = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_project(self, payload: JsonObject) -> JsonObject:
        now = utc_now()
        project_id = str(uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO projects (
                  id, user_id, source_type, source_url, source_file_path, platform,
                  title, notes, extraction_preference, status, error_message, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    payload.get("user_id") or "local-user",
                    payload["source_type"],
                    payload.get("source_url"),
                    payload.get("source_file_path"),
                    payload.get("platform") or "unknown",
                    payload.get("title") or "未命名项目",
                    payload.get("notes") or "",
                    payload.get("extraction_preference") or "auto",
                    "queued",
                    None,
                    now,
                    now,
                ),
            )
        project = self.get_project(project_id)
        if project is None:
            raise RuntimeError("created project was not found")
        return project

    def list_projects(self) -> list[JsonObject]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY created_at DESC"
            ).fetchall()
        return [self._project_from_row(row) for row in rows]

    def get_project(self, project_id: str) -> JsonObject | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return self._project_from_row(row) if row else None

    def get_project_detail(self, project_id: str) -> JsonObject | None:
        project = self.get_project(project_id)
        if project is None:
            return None
        project["transcript"] = self.get_transcript(project_id)
        project["analysis"] = self.get_analysis(project_id)
        project["scripts"] = self.list_scripts(project_id)
        project["render_jobs"] = self.list_render_jobs(project_id)
        return project

    def update_project_status(self, project_id: str, status: str, error_message: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE projects
                SET status = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, error_message, utc_now(), project_id),
            )

    def save_transcript(self, project_id: str, transcript: JsonObject) -> JsonObject:
        now = utc_now()
        with self.connect() as conn:
            conn.execute("DELETE FROM transcripts WHERE project_id = ?", (project_id,))
            transcript_id = str(uuid4())
            conn.execute(
                """
                INSERT INTO transcripts (
                  id, project_id, raw_text, segments_json, language,
                  asr_provider, extraction_method, warnings_json, subtitle_file_url, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transcript_id,
                    project_id,
                    transcript["raw_text"],
                    json.dumps(transcript.get("segments") or [], ensure_ascii=False),
                    transcript.get("language") or "zh",
                    transcript.get("provider") or "unknown",
                    transcript.get("extraction_method") or "speech",
                    json.dumps(transcript.get("warnings") or [], ensure_ascii=False),
                    transcript.get("subtitle_file_url"),
                    now,
                    now,
                ),
            )
        saved = self.get_transcript(project_id)
        if saved is None:
            raise RuntimeError("saved transcript was not found")
        return saved

    def get_transcript(self, project_id: str) -> JsonObject | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM transcripts WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "raw_text": row["raw_text"],
            "segments": json.loads(row["segments_json"]),
            "language": row["language"],
            "asr_provider": row["asr_provider"],
            "extraction_method": row["extraction_method"],
            "warnings": json.loads(row["warnings_json"]),
            "subtitle_file_url": row["subtitle_file_url"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def update_transcript_text(self, project_id: str, raw_text: str) -> JsonObject | None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE transcripts
                SET raw_text = ?, updated_at = ?
                WHERE project_id = ?
                """,
                (raw_text, utc_now(), project_id),
            )
        return self.get_transcript(project_id)

    def save_analysis(self, project_id: str, analysis: JsonObject) -> JsonObject:
        now = utc_now()
        with self.connect() as conn:
            conn.execute("DELETE FROM analyses WHERE project_id = ?", (project_id,))
            analysis_id = str(uuid4())
            conn.execute(
                """
                INSERT INTO analyses (
                  id, project_id, topic, audience, category, hook, structure_json,
                  key_points_json, risks_json, provider, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    project_id,
                    analysis.get("topic"),
                    analysis.get("audience"),
                    analysis.get("category"),
                    analysis.get("hook"),
                    json.dumps(analysis.get("structure") or [], ensure_ascii=False),
                    json.dumps(analysis.get("key_points") or [], ensure_ascii=False),
                    json.dumps(analysis.get("risks") or [], ensure_ascii=False),
                    analysis.get("provider") or "unknown",
                    now,
                ),
            )
        saved = self.get_analysis(project_id)
        if saved is None:
            raise RuntimeError("saved analysis was not found")
        return saved

    def get_analysis(self, project_id: str) -> JsonObject | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM analyses WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "topic": row["topic"],
            "audience": row["audience"],
            "category": row["category"],
            "hook": row["hook"],
            "structure": json.loads(row["structure_json"]),
            "key_points": json.loads(row["key_points_json"]),
            "risks": json.loads(row["risks_json"]),
            "provider": row["provider"],
            "created_at": row["created_at"],
        }

    def replace_scripts(self, project_id: str, scripts: list[JsonObject]) -> list[JsonObject]:
        now = utc_now()
        with self.connect() as conn:
            conn.execute("DELETE FROM scripts WHERE project_id = ?", (project_id,))
            for item in scripts:
                conn.execute(
                    """
                    INSERT INTO scripts (
                      id, project_id, version, script_text, storyboard_json,
                      title_options_json, cover_text_options_json, tags_json,
                      status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        project_id,
                        item["version"],
                        item["script_text"],
                        json.dumps(item.get("storyboard") or [], ensure_ascii=False),
                        json.dumps(item.get("title_options") or [], ensure_ascii=False),
                        json.dumps(item.get("cover_text_options") or [], ensure_ascii=False),
                        json.dumps(item.get("tags") or [], ensure_ascii=False),
                        "draft",
                        now,
                        now,
                    ),
                )
        return self.list_scripts(project_id)

    def list_scripts(self, project_id: str) -> list[JsonObject]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scripts WHERE project_id = ? ORDER BY version",
                (project_id,),
            ).fetchall()
        return [self._script_from_row(row) for row in rows]

    def get_script(self, script_id: str) -> JsonObject | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM scripts WHERE id = ?", (script_id,)).fetchone()
        return self._script_from_row(row) if row else None

    def update_script(self, script_id: str, script_text: str) -> JsonObject | None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE scripts
                SET script_text = ?, updated_at = ?
                WHERE id = ?
                """,
                (script_text, utc_now(), script_id),
            )
        return self.get_script(script_id)

    def approve_script(self, script_id: str) -> JsonObject | None:
        script = self.get_script(script_id)
        if script is None:
            return None
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE scripts
                SET status = 'draft', updated_at = ?
                WHERE project_id = ? AND id != ?
                """,
                (now, script["project_id"], script_id),
            )
            conn.execute(
                """
                UPDATE scripts
                SET status = 'approved', updated_at = ?
                WHERE id = ?
                """,
                (now, script_id),
            )
        return self.get_script(script_id)

    def create_render_job(self, script: JsonObject, provider: str) -> JsonObject:
        now = utc_now()
        render_job_id = str(uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO render_jobs (
                  id, project_id, script_id, provider, status, output_video_url,
                  error_message, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    render_job_id,
                    script["project_id"],
                    script["id"],
                    provider,
                    "queued",
                    None,
                    None,
                    now,
                    now,
                ),
            )
        job = self.get_render_job(render_job_id)
        if job is None:
            raise RuntimeError("created render job was not found")
        return job

    def get_render_job(self, render_job_id: str) -> JsonObject | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM render_jobs WHERE id = ?",
                (render_job_id,),
            ).fetchone()
        return self._render_job_from_row(row) if row else None

    def list_render_jobs(self, project_id: str) -> list[JsonObject]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM render_jobs WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [self._render_job_from_row(row) for row in rows]

    def update_render_job(
        self,
        render_job_id: str,
        status: str,
        output_video_url: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE render_jobs
                SET status = ?, output_video_url = COALESCE(?, output_video_url),
                    error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, output_video_url, error_message, utc_now(), render_job_id),
            )

    @staticmethod
    def _project_from_row(row: sqlite3.Row) -> JsonObject:
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "source_type": row["source_type"],
            "source_url": row["source_url"],
            "source_file_path": row["source_file_path"],
            "platform": row["platform"],
            "title": row["title"],
            "notes": row["notes"],
            "extraction_preference": row["extraction_preference"],
            "status": row["status"],
            "error_message": row["error_message"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _script_from_row(row: sqlite3.Row) -> JsonObject:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "version": row["version"],
            "script_text": row["script_text"],
            "storyboard": json.loads(row["storyboard_json"]),
            "title_options": json.loads(row["title_options_json"]),
            "cover_text_options": json.loads(row["cover_text_options_json"]),
            "tags": json.loads(row["tags_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _render_job_from_row(row: sqlite3.Row) -> JsonObject:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "script_id": row["script_id"],
            "provider": row["provider"],
            "status": row["status"],
            "output_video_url": row["output_video_url"],
            "error_message": row["error_message"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
