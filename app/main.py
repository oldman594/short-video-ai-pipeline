from __future__ import annotations

import base64
import json
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

from app.config import DB_PATH, OUTPUT_DIR, STATIC_DIR, UPLOAD_DIR, ensure_directories
from app.providers import MockAvatarVideoProvider
from app.storage import Repository
from app.text_extraction import VALID_EXTRACTION_PREFERENCES, text_extraction_tool_status
from app.workflow import BackgroundRunner, WorkflowService


MAX_JSON_BODY_BYTES = 50 * 1024 * 1024


def create_app_state() -> tuple[Repository, WorkflowService, BackgroundRunner]:
    ensure_directories()
    repository = Repository(DB_PATH)
    repository.init_schema()
    workflow = WorkflowService(repository)
    runner = BackgroundRunner(workflow)
    return repository, workflow, runner


REPOSITORY, WORKFLOW, RUNNER = create_app_state()


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "ShortVideoMVP/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._serve_static("index.html")
        elif path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
        elif path in {"/app.js", "/styles.css"}:
            self._serve_static(path.lstrip("/"))
        elif path == "/api/projects":
            self._json_response({"projects": REPOSITORY.list_projects()})
        elif path == "/api/system/text-extraction-tools":
            self._json_response(text_extraction_tool_status())
        elif match := re.fullmatch(r"/api/projects/([^/]+)", path):
            project = REPOSITORY.get_project_detail(match.group(1))
            if project is None:
                self._error(HTTPStatus.NOT_FOUND, "project not found")
                return
            self._json_response(project)
        elif match := re.fullmatch(r"/api/render-jobs/([^/]+)", path):
            job = REPOSITORY.get_render_job(match.group(1))
            if job is None:
                self._error(HTTPStatus.NOT_FOUND, "render job not found")
                return
            self._json_response(job)
        elif path.startswith("/outputs/"):
            self._serve_output(path.removeprefix("/outputs/"))
        else:
            self._error(HTTPStatus.NOT_FOUND, "route not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/projects":
            self._create_project()
        elif match := re.fullmatch(r"/api/scripts/([^/]+)/approve", path):
            self._approve_script(match.group(1))
        elif match := re.fullmatch(r"/api/scripts/([^/]+)/render", path):
            self._render_script(match.group(1))
        else:
            self._error(HTTPStatus.NOT_FOUND, "route not found")

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if match := re.fullmatch(r"/api/projects/([^/]+)/transcript", path):
            self._update_transcript(match.group(1))
        elif match := re.fullmatch(r"/api/scripts/([^/]+)", path):
            self._update_script(match.group(1))
        else:
            self._error(HTTPStatus.NOT_FOUND, "route not found")

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _create_project(self) -> None:
        payload = self._read_json()
        if payload is None:
            return
        source_type = payload.get("source_type") or payload.get("sourceType")
        if source_type not in {"link", "upload"}:
            self._error(HTTPStatus.BAD_REQUEST, "source_type must be link or upload")
            return
        extraction_preference = (
            payload.get("extraction_preference")
            or payload.get("extractionPreference")
            or "auto"
        )
        if extraction_preference not in VALID_EXTRACTION_PREFERENCES:
            self._error(HTTPStatus.BAD_REQUEST, "unknown extraction_preference")
            return

        source_file_path = None
        file_payload = payload.get("file") or {}
        if source_type == "upload" or file_payload:
            try:
                source_file_path = self._save_upload(file_payload)
            except ValueError as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
                return

        project = REPOSITORY.create_project(
            {
                "source_type": source_type,
                "source_url": payload.get("source_url") or payload.get("sourceUrl"),
                "source_file_path": source_file_path,
                "platform": payload.get("platform"),
                "title": payload.get("title"),
                "notes": payload.get("notes"),
                "extraction_preference": extraction_preference,
            }
        )
        RUNNER.enqueue_project(project["id"])
        self._json_response(project, HTTPStatus.CREATED)

    def _update_transcript(self, project_id: str) -> None:
        payload = self._read_json()
        if payload is None:
            return
        raw_text = payload.get("raw_text") or payload.get("rawText")
        if not isinstance(raw_text, str) or not raw_text.strip():
            self._error(HTTPStatus.BAD_REQUEST, "raw_text is required")
            return
        transcript = REPOSITORY.update_transcript_text(project_id, raw_text)
        if transcript is None:
            self._error(HTTPStatus.NOT_FOUND, "transcript not found")
            return
        self._json_response(transcript)

    def _update_script(self, script_id: str) -> None:
        payload = self._read_json()
        if payload is None:
            return
        script_text = payload.get("script_text") or payload.get("scriptText")
        if not isinstance(script_text, str) or not script_text.strip():
            self._error(HTTPStatus.BAD_REQUEST, "script_text is required")
            return
        script = REPOSITORY.update_script(script_id, script_text)
        if script is None:
            self._error(HTTPStatus.NOT_FOUND, "script not found")
            return
        self._json_response(script)

    def _approve_script(self, script_id: str) -> None:
        script = REPOSITORY.approve_script(script_id)
        if script is None:
            self._error(HTTPStatus.NOT_FOUND, "script not found")
            return
        self._json_response(script)

    def _render_script(self, script_id: str) -> None:
        script = REPOSITORY.get_script(script_id)
        if script is None:
            self._error(HTTPStatus.NOT_FOUND, "script not found")
            return
        if script["status"] != "approved":
            self._error(HTTPStatus.CONFLICT, "script must be approved before rendering")
            return
        job = REPOSITORY.create_render_job(script, MockAvatarVideoProvider.name)
        RUNNER.enqueue_render(script_id, job["id"])
        self._json_response(job, HTTPStatus.ACCEPTED)

    def _read_json(self) -> dict | None:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError:
            self._error(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
            return None
        if length <= 0:
            return {}
        if length > MAX_JSON_BODY_BYTES:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body is too large")
            return None
        raw_body = self.rfile.read(length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._error(HTTPStatus.BAD_REQUEST, "invalid JSON body")
            return None
        if not isinstance(payload, dict):
            self._error(HTTPStatus.BAD_REQUEST, "JSON body must be an object")
            return None
        return payload

    def _save_upload(self, file_payload: dict) -> str:
        filename = self._safe_filename(file_payload.get("filename") or "upload.bin")
        content_base64 = file_payload.get("content_base64") or file_payload.get("contentBase64")
        if not isinstance(content_base64, str) or not content_base64:
            raise ValueError("upload file content_base64 is required")
        if "," in content_base64:
            content_base64 = content_base64.split(",", 1)[1]
        try:
            content = base64.b64decode(content_base64, validate=True)
        except ValueError as exc:
            raise ValueError("upload file content_base64 is invalid") from exc
        upload_path = UPLOAD_DIR / f"{uuid4()}-{filename}"
        upload_path.write_bytes(content)
        return str(upload_path)

    @staticmethod
    def _safe_filename(filename: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip(".-")
        return safe or "upload.bin"

    def _serve_static(self, filename: str) -> None:
        path = (STATIC_DIR / filename).resolve()
        if not path.is_file() or STATIC_DIR.resolve() not in path.parents:
            self._error(HTTPStatus.NOT_FOUND, "static file not found")
            return
        self._serve_file(path)

    def _serve_output(self, filename: str) -> None:
        safe_name = Path(unquote(filename)).name
        path = (OUTPUT_DIR / safe_name).resolve()
        if not path.is_file() or OUTPUT_DIR.resolve() not in path.parents:
            self._error(HTTPStatus.NOT_FOUND, "output file not found")
            return
        self._serve_file(path, download_name=safe_name)

    def _serve_file(self, path: Path, download_name: str | None = None) -> None:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        self.wfile.write(content)

    def _json_response(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json_response({"error": message}, status)


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"Short Video AI Pipeline MVP running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
