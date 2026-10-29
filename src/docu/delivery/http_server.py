"""Transporte HTTP sobre el mismo servidor MCP: JSON-RPC 2.0 por POST.

Que quede claro lo que **no** es: no implementa el transporte «Streamable HTTP» del estándar MCP,
que requiere mensajes servidor→cliente por SSE. Es un puente JSON-RPC para scripts, integraciones y
equipos que necesitan consultar la documentación de un proyecto desde otro proceso o máquina.

Endpoints:
  POST /mcp        cuerpo JSON-RPC → una respuesta JSON (204 si la petición era una notificación)
  GET  /health     estado y proyectos servidos
  GET  /projects   lista de proyectos
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from docu.delivery.mcp_server import PROTOCOL_VERSION, McpServer

DEFAULT_HOST = "127.0.0.1"
MAX_BODY_BYTES = 1_000_000


class _Handler(BaseHTTPRequestHandler):
    server_version = "docu-mcp-http/0.1"
    mcp: McpServer  # inyectado por clase antes de servir

    # ------------------------------------------------------------------ rutas

    def do_GET(self) -> None:  # noqa: N802 - API de BaseHTTPRequestHandler
        if self.path.rstrip("/") in ("/health", ""):
            self._json(
                200,
                {
                    "status": "ok",
                    "protocol_version": PROTOCOL_VERSION,
                    "projects": [
                        {"name": ref.name, "documented": ref.has_docs} for ref in self.mcp.projects()
                    ],
                },
            )
            return
        if self.path.rstrip("/") == "/projects":
            payload = self.mcp.call_tool("list_projects", {})
            self._json(200, payload)
            return
        self._json(404, {"error": f"ruta desconocida: {self.path}"})

    def do_POST(self) -> None:  # noqa: N802 - API de BaseHTTPRequestHandler
        if self.path.rstrip("/") != "/mcp":
            self._json(404, {"error": f"ruta desconocida: {self.path}"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "cuerpo vacío"}})
            return
        if length > MAX_BODY_BYTES:
            self._json(413, {"error": "cuerpo demasiado grande"})
            return
        raw = self.rfile.read(length)
        try:
            request = json.loads(raw)
        except json.JSONDecodeError as error:
            self._json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"JSON inválido: {error}"}})
            return
        if not isinstance(request, dict):
            self._json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "se esperaba un objeto"}})
            return
        response = self.mcp.handle(request)
        if response is None:
            self.send_response(204)
            self.end_headers()
            return
        self._json(200, response)

    # ------------------------------------------------------------------ utilidades

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:  # silencio: el servidor habla por stderr
        print(f"[mcp-http] {fmt % args}", file=sys.stderr)


def make_server(server: McpServer, host: str = DEFAULT_HOST, port: int = 8765) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (_Handler,), {"mcp": server})
    return ThreadingHTTPServer((host, port), handler)


def serve_http(
    server: McpServer,
    host: str = DEFAULT_HOST,
    port: int = 8765,
    *,
    blocking: bool = True,
) -> tuple[ThreadingHTTPServer, str]:
    """Arranca el puente HTTP. Devuelve el servidor y su URL base."""
    httpd = make_server(server, host, port)
    actual_port = httpd.server_address[1]
    url = f"http://{host}:{actual_port}"
    print(f"MCP HTTP escuchando en {url} (POST /mcp · GET /health)", file=sys.stderr)
    if blocking:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:  # pragma: no cover - interacción de consola
            pass
    return httpd, url


__all__ = ["DEFAULT_HOST", "make_server", "serve_http"]
