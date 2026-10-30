"""Servidor MCP: solo lectura, protocolo correcto y errores que no tumban el proceso."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from docu.delivery.mcp_server import (
    PROTOCOL_VERSION,
    READ_ONLY_TOOLS,
    TOOL_DEFINITIONS,
    McpServer,
    ToolError,
    build_server,
)

DOC = """# demo — Manual técnico

## 4. API HTTP

| Verbo | Ruta | Cita |
|---|---|---|
| POST | `/api/auth/refresh` | `Auth.java#L35-L40` |

## 8. Trazabilidad

Sin evidencia disponible en esta sección.

> **Sin evidencia disponible.** Esta sección no se documenta.
"""


def build_docs(root: Path) -> Path:
    docs = root / "docs" / "generated"
    docs.mkdir(parents=True)
    (docs / "l1-manual-tecnico.md").write_text(DOC, encoding="utf-8")
    return docs


class ProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.docs = build_docs(self.root)
        self.server = build_server(self.root, self.docs)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_initialize(self) -> None:
        response = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert response is not None
        self.assertEqual(response["result"]["protocolVersion"], PROTOCOL_VERSION)
        self.assertEqual(response["result"]["serverInfo"]["name"], "docu")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_notification_has_no_response(self) -> None:
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_tools_list_is_read_only(self) -> None:
        response = self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert response is not None
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertEqual(names, set(READ_ONLY_TOOLS))
        for tool in TOOL_DEFINITIONS:
            self.assertIn("inputSchema", tool)

    def test_unknown_method_returns_error(self) -> None:
        response = self.server.handle({"jsonrpc": "2.0", "id": 3, "method": "recursos/listar"})
        assert response is not None
        self.assertEqual(response["error"]["code"], -32601)

    def test_ping(self) -> None:
        response = self.server.handle({"jsonrpc": "2.0", "id": 4, "method": "ping"})
        assert response is not None
        self.assertEqual(response["result"], {})


class ToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.docs = build_docs(self.root)
        # Fixture mínimo para `verify_citation` y `get_diagram`.
        (self.root / "src").mkdir(exist_ok=True)
        (self.root / "src" / "app.py").write_text(
            "class App:\n    def run(self):\n        return 1\n", encoding="utf-8"
        )
        diagrams = self.docs / "diagrams"
        diagrams.mkdir(exist_ok=True)
        (diagrams / "arquitectura.mmd").write_text(
            'flowchart LR\n    a["a"]\n    b["b"]\n    a --> b\n', encoding="utf-8"
        )
        self.server = build_server(self.root, self.docs)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _call(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        response = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        assert response is not None
        content = response["result"]["content"][0]["text"]
        return json.loads(content)

    def test_list_projects_uses_the_documented_name(self) -> None:
        """F-05: devolvía `name: ""` porque no leía el nombre del manifest."""
        payload = self._call("list_projects", {})
        self.assertTrue(payload["projects"])
        for project in payload["projects"]:
            self.assertTrue(project["name"], msg="el nombre no puede venir vacío")

    def test_verify_citation_accepts_a_valid_range(self) -> None:
        payload = self._call("verify_citation", {"citation": "src/app.py#L1-L3"})
        self.assertTrue(payload["ok"])
        self.assertIn("class", payload["content"])

    def test_verify_citation_rejects_a_missing_file(self) -> None:
        payload = self._call("verify_citation", {"citation": "src/noexiste.py#L1-L2"})
        self.assertFalse(payload["ok"])
        self.assertIn("no existe", payload["reason"])

    def test_verify_citation_rejects_a_bad_range(self) -> None:
        payload = self._call("verify_citation", {"citation": "src/app.py#L1-L9999"})
        self.assertFalse(payload["ok"])
        self.assertIn("rango", payload["reason"])

    def test_verify_citation_requires_the_format(self) -> None:
        with self.assertRaises(ToolError):
            self.server.call_tool("verify_citation", {"citation": "src/app.py"})

    def test_get_diagram_lists_and_returns(self) -> None:
        listing = self._call("get_diagram", {})
        self.assertIn("arquitectura", listing["available"])
        payload = self._call("get_diagram", {"name": "arquitectura"})
        self.assertIn("flowchart", payload["mermaid"])

    def test_get_diagram_rejects_unknown_name(self) -> None:
        with self.assertRaises(ToolError):
            self.server.call_tool("get_diagram", {"name": "no-existe"})

    def test_list_unsupported_reports_languages_and_gaps(self) -> None:
        payload = self._call("list_unsupported", {})
        self.assertIn("unsupported_languages", payload)
        self.assertIn("sections_without_evidence", payload)
        self.assertIsInstance(payload["uncitable_facts"], int)

    def test_search_docs_returns_citations(self) -> None:
        payload = self._call("search_docs", {"query": "refresh token"})
        self.assertGreater(payload["total"], 0)
        self.assertIn("Auth.java#L35-L40", payload["results"][0]["citations"])

    def test_search_docs_requires_query(self) -> None:
        with self.assertRaises(ToolError):
            self.server.call_tool("search_docs", {})

    def test_get_module(self) -> None:
        payload = self._call("get_module", {"name": "api"})
        self.assertEqual(payload["heading"], "4. API HTTP")

    def test_get_symbol_doc(self) -> None:
        payload = self._call("get_symbol_doc", {"symbol": "refresh"})
        self.assertTrue(payload["evidence"])

    def test_list_gaps(self) -> None:
        payload = self._call("list_gaps", {})
        self.assertGreaterEqual(payload["total"], 1)
        self.assertIn("Trazabilidad", payload["gaps"][0]["heading"])

    def test_get_freshness(self) -> None:
        payload = self._call("get_freshness", {})
        self.assertIn("states", payload)
        self.assertIn("l1", payload["states"])

    def test_get_architecture_without_model_is_an_error(self) -> None:
        payload = self._call("get_architecture", {})
        self.assertIn("error", payload)

    def test_get_architecture_with_model(self) -> None:
        (self.root / "architecture.yaml").write_text(
            "architecture:\n"
            "  components:\n"
            "    - name: Auth\n"
            '      provides: ["POST /api/auth/refresh"]\n'
            "      depends_on: [Tokens]\n",
            encoding="utf-8",
        )
        payload = self._call("get_architecture", {})
        self.assertEqual(payload["components"][0]["name"], "Auth")
        self.assertIn("POST /api/auth/refresh", payload["components"][0]["provides"])

    def test_unknown_tool_is_rejected(self) -> None:
        response = self.server.handle(
            {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": "borrar_todo"}}
        )
        assert response is not None
        self.assertEqual(response["error"]["code"], -32602)

    def test_tools_never_modify_files(self) -> None:
        def snapshot() -> dict[str, int]:
            return {
                str(path): path.stat().st_mtime_ns
                for path in sorted(self.docs.rglob("*.md"))
            }

        before = snapshot()
        for name in READ_ONLY_TOOLS:
            try:
                self.server.call_tool(name, {"query": "api", "name": "api", "symbol": "refresh"})
            except ToolError:
                pass
        self.assertEqual(before, snapshot())


class StdioTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.docs = build_docs(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_line_protocol(self) -> None:
        server = build_server(self.root, self.docs)
        stream = io.StringIO(
            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
            "\n"
            "no es json\n"
            '{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
        )
        output = io.StringIO()
        self.assertEqual(server.serve(stream, output), 0)
        lines = [json.loads(line) for line in output.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0]["result"]["protocolVersion"], PROTOCOL_VERSION)
        self.assertEqual(lines[1]["error"]["code"], -32700)
        self.assertEqual(lines[2]["id"], 2)

    def test_missing_documents_reports_actionable_error(self) -> None:
        server = build_server(self.root, self.root / "no-existe")
        payload = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "search_docs", "arguments": {"query": "x"}},
            }
        )
        assert payload is not None
        self.assertTrue(payload["result"]["isError"])
        self.assertIn("docu gen", payload["result"]["content"][0]["text"])


class WorkspaceTests(unittest.TestCase):
    """Un servidor, varios repositorios: la consulta cruza proyectos sin reconfigurar nada."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        self.alpha = self.workspace / "alpha"
        self.beta = self.workspace / "beta"
        for project, heading in ((self.alpha, "Alpha API"), (self.beta, "Beta API")):
            docs = project / "docs" / "generated"
            docs.mkdir(parents=True)
            (docs / "l1-manual-tecnico.md").write_text(
                f"# {project.name}\n\n## {heading}\n\n| Ruta | Cita |\n|---|---|\n"
                f"| `/{project.name}` | `A.java#L1-L2` |\n",
                encoding="utf-8",
            )
        # Proyecto sin documentación: debe aparecer como no documentado, no desaparecer.
        (self.workspace / "gamma").mkdir()
        self.server = build_server(self.workspace, workspace=self.workspace)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _call(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        response = self.server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        )
        assert response is not None
        return json.loads(response["result"]["content"][0]["text"])

    def test_discovers_documented_projects(self) -> None:
        payload = self._call("list_projects", {})
        names = {project["name"] for project in payload["projects"]}
        self.assertEqual(names, {"alpha", "beta"})

    def test_requires_project_when_several_are_served(self) -> None:
        payload = self._call("search_docs", {"query": "api"})
        self.assertIn("error", payload)
        self.assertIn("project", payload["error"])

    def test_query_targets_a_specific_project(self) -> None:
        payload = self._call("search_docs", {"query": "api", "project": "beta"})
        self.assertEqual(payload["project"], "beta")
        self.assertEqual(payload["results"][0]["heading"], "Beta API")

    def test_unknown_project_lists_available(self) -> None:
        payload = self._call("search_docs", {"query": "api", "project": "delta"})
        self.assertIn("desconocido", payload["error"])
        self.assertIn("alpha", payload["error"])

    def test_freshness_is_per_project(self) -> None:
        payload = self._call("get_freshness", {"project": "alpha"})
        self.assertIn("states", payload)
        self.assertEqual(payload["project"], "alpha")

    def test_single_project_needs_no_selector(self) -> None:
        server = build_server(self.alpha, workspace=self.alpha)
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "search_docs", "arguments": {"query": "api"}},
            }
        )
        assert response is not None
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["project"], "alpha")

    def test_tools_list_includes_projects_tool(self) -> None:
        response = self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert response is not None
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertIn("list_projects", names)
        search = next(tool for tool in response["result"]["tools"] if tool["name"] == "search_docs")
        self.assertIn("project", search["inputSchema"]["properties"])


class CodeSearchToolTests(unittest.TestCase):
    """`search_code` expone el índice híbrido del producto, no el Markdown generado."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        package = self.root / "src" / "demo"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "freshness.py").write_text(
            'def classify(stored: str | None, current: str) -> str:\n'
            '    """Decide si una página está desactualizada."""\n'
            '    if stored != current:\n        return "stale"\n    return "fresh"\n',
            encoding="utf-8",
        )
        self.server = build_server(self.root, self.root / "docs", dense=False)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _call(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        response = self.server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        )
        assert response is not None
        return json.loads(response["result"]["content"][0]["text"])

    def test_search_code_returns_cited_chunks(self) -> None:
        payload = self._call("search_code", {"query": "página desactualizada"})
        self.assertFalse(payload.get("capabilities", {}).get("dense"))
        first = payload["results"][0]  # type: ignore[index]
        self.assertIn("freshness.py#L", first["citation"])
        self.assertEqual(first["symbol"], "classify")

    def test_search_code_requires_query(self) -> None:
        with self.assertRaises(ToolError):
            self.server.call_tool("search_code", {})

    def test_search_code_reports_no_match(self) -> None:
        payload = self._call("search_code", {"query": "ornitorrinco"})
        self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
