from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.main import RequestHandler


class ApiValidationTest(unittest.TestCase):
    def test_create_project_rejects_unknown_extraction_preference(self) -> None:
        # Test objective:
        # Verify that the HTTP API rejects unsupported text extraction preferences
        # before a project is accepted into the background workflow.
        #
        # Construction method:
        # 1. Start the standard RequestHandler on an ephemeral local port.
        # 2. Submit the same JSON shape used by the browser create-project form.
        # 3. Use an invalid extraction_preference value that is outside the router contract.
        #
        # Input data:
        # A link project with extraction_preference set to "unsupported".
        #
        # Expected behavior:
        # The API returns HTTP 400 with an error message, and no successful project
        # creation response is produced.
        server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)

        payload = json.dumps(
            {
                "source_type": "link",
                "title": "非法偏好测试",
                "platform": "web",
                "source_url": "https://example.test/video",
                "extraction_preference": "unsupported",
            }
        ).encode("utf-8")

        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/projects",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )

        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=5)

        self.assertEqual(raised.exception.code, 400)
        body = json.loads(raised.exception.read().decode("utf-8"))
        raised.exception.close()
        self.assertEqual(body["error"], "unknown extraction_preference")

    def test_create_link_project_accepts_optional_uploaded_media(self) -> None:
        # Test objective:
        # Verify that link projects can carry a user-provided media file to the server
        # so server-side text extraction can operate without downloading the platform URL.
        #
        # Construction method:
        # 1. Start the standard RequestHandler on an ephemeral local port.
        # 2. Submit a link project JSON payload with an attached base64 text payload.
        # 3. Read the create-project response.
        #
        # Input data:
        # A source URL plus a small attached file field, matching the browser upload shape.
        #
        # Expected behavior:
        # The API returns HTTP 201 and stores a source_file_path even though source_type
        # remains "link".
        server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)

        payload = json.dumps(
            {
                "source_type": "link",
                "title": "链接附带文件测试",
                "platform": "douyin",
                "source_url": "https://www.douyin.com/video/123",
                "extraction_preference": "auto",
                "file": {
                    "filename": "sample.txt",
                    "content_base64": "5pys5Zyw5paH5Lu25YaF5a65",
                },
            }
        ).encode("utf-8")

        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/projects",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        response = urlopen(request, timeout=5)
        body = json.loads(response.read().decode("utf-8"))
        response.close()

        self.assertEqual(response.status, 201)
        self.assertEqual(body["source_type"], "link")
        self.assertTrue(body["source_file_path"])


if __name__ == "__main__":
    unittest.main()
