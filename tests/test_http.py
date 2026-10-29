"""Puente HTTP: JSON-RPC por POST sobre el mismo servidor MCP, sin reimplementar nada."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from docu.delivery.http_server import serve_http
from docu.delivery.mcp_server import build_server

DOC = """# demo

## 4. API HTTP

| Verbo | Ruta | Cita |
|---|---|---|
| GET | `/ping` | `A.java#L1-L2` |
"""


def build_docs(root: Path) -> Path:
    docs = root / "docs" / "generated"
    docs.mkdir(parents=True)
    (docs / "l1-manual-tecnico.md").write_text(DOC, encoding="utf-8")
    return docs


class HttpBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        docs = build_docs(self.root)
        self.server = build_server(self.root, docs, dense=False)
        self.httpd, self.url = serve_http(self.server, host="127.0.0.1", port=0, blocking=False)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self._tmp.cleanup()

    # ------------------------------------------------------------------ utilidades

    def _post(self, payload: object, path: str = "/mcp") -> tuple[int, dict[str, object] | None]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.url}{path}", data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raw = error.read()
            return error.code, json.loads(raw) if raw else None

    def _get(self, path: str) -> tuple[int, dict[str, object]]:
        with urllib.request.urlopen(f"{self.url}{path}", timeout=5) as response:
            return response.status, json.loads(response.read())

    # ------------------------------------------------------------------ pruebas

    def test_health_reports_projects(self) -> None:
        status, payload = self._get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["projects"][0]["name"], self.root.name)

    def test_projects_endpoint(self) -> None:
        status, payload = self._get("/projects")
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 1)

    def test_tools_list_over_http(self) -> None:
        status, payload = self._post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(status, 200)
        assert payload is not None
        names = {tool["name"] for tool in payload["result"]["tools"]}  # type: ignore[index]
        self.assertIn("search_code", names)

    def test_tool_call_over_http(self) -> None:
        status, payload = self._post(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "search_docs", "arguments": {"query": "ping"}},
            }
        )
        self.assertEqual(status, 200)
        assert payload is not None
        content = json.loads(payload["result"]["content"][0]["text"])  # type: ignore[index]
        self.assertGreater(content["total"], 0)

    def test_notification_returns_no_content(self) -> None:
        status, payload = self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(status, 204)
        self.assertIsNone(payload)

    def test_invalid_json_is_rejected(self) -> None:
        request = urllib.request.Request(
            f"{self.url}/mcp", data=b"{no json", headers={"Content-Type": "application/json"}, method="POST"
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(context.exception.code, 400)

    def test_unknown_path_returns_404(self) -> None:
        status, payload = self._post({"jsonrpc": "2.0", "id": 1, "method": "ping"}, path="/otra")
        self.assertEqual(status, 404)
        assert payload is not None
        self.assertIn("error", payload)

    def test_empty_body_is_rejected(self) -> None:
        request = urllib.request.Request(
            f"{self.url}/mcp", data=b"", headers={"Content-Type": "application/json"}, method="POST"
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(context.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
