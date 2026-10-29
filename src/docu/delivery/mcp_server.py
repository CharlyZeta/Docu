"""Servidor MCP de solo lectura (Model Context Protocol).

Permite que un agente de codigo (Cursor, Claude Code) consulte **la misma documentación** que leen
los humanos, con las mismas citas. Sin escritura: el servidor no puede modificar el repositorio ni
el manifest, solo leerlos. La autonomía de escritura vive en el CLI y en su compuerta.

Transporte: JSON-RPC 2.0 por stdio, un objeto por linea (el que usa MCP).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from docu import __version__
from docu.conformance.model import load_architecture
from docu.generate.pipeline import inspect
from docu.generate.markdown import NO_EVIDENCE_MARKER
from docu.retrieve.search import DocIndex

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "docu"

READ_ONLY_TOOLS = (
    "list_projects",
    "search_code",
    "search_docs",
    "get_module",
    "get_symbol_doc",
    "list_gaps",
    "get_architecture",
    "get_freshness",
)

#: Esquema comun: todas las herramientas aceptan `project` cuando el servidor sirve varios repos.
PROJECT_PROPERTY: dict[str, Any] = {
    "type": "string",
    "description": "Proyecto a consultar cuando el servidor sirve un workspace (ver list_projects)",
}

TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "search_code",
        "description": (
            "Busca en el código real con recuperación híbrida (léxico + símbolo + denso) y devuelve "
            "los fragmentos con su cita. Es la vía recomendada para preguntas técnicas; "
            "`search_docs` sirve para la documentación ya redactada."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
                "project": PROJECT_PROPERTY,
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_projects",
        "description": "Lista los proyectos servidos por este servidor y si tienen documentación.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_docs",
        "description": "Busca en la documentación generada y devuelve secciones con su cita (archivo#L).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Pregunta o términos de búsqueda"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                "level": {
                    "type": "string",
                    "enum": ["l1", "l3", "l4"],
                    "description": "Restringe a un nivel de audiencia",
                },
                "project": PROJECT_PROPERTY,
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_module",
        "description": "Devuelve la documentación de un módulo, paquete o componente por su nombre.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "project": PROJECT_PROPERTY},
            "required": ["name"],
        },
    },
    {
        "name": "get_symbol_doc",
        "description": "Devuelve la evidencia documentada de un símbolo de código y su ubicación.",
        "inputSchema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}, "project": PROJECT_PROPERTY},
            "required": ["symbol"],
        },
    },
    {
        "name": "list_gaps",
        "description": "Lista las secciones que el agente declaró sin evidencia (huecos, no invenciones).",
        "inputSchema": {"type": "object", "properties": {"project": PROJECT_PROPERTY}},
    },
    {
        "name": "get_architecture",
        "description": "Devuelve el modelo arquitectónico declarado: componentes, rutas y dependencias.",
        "inputSchema": {"type": "object", "properties": {"project": PROJECT_PROPERTY}},
    },
    {
        "name": "get_freshness",
        "description": "Estado de frescura de cada nivel (fresh/stale/expired) según el manifest.",
        "inputSchema": {"type": "object", "properties": {"project": PROJECT_PROPERTY}},
    },
)


@dataclass(frozen=True, slots=True)
class ProjectRef:
    """Un proyecto servido: su raíz y el directorio con la documentación generada."""

    name: str
    root: Path
    docs_dir: Path

    @property
    def has_docs(self) -> bool:
        return self.docs_dir.exists() and any(self.docs_dir.glob("*.md"))


class ToolError(Exception):
    """Error de negocio del servidor: se devuelve como contenido de error, no como caída."""


@dataclass
class McpServer:
    """Servidor de solo lectura sobre **uno o varios** proyectos documentados.

    Con `workspace` apunta a una carpeta que contiene repositorios; cada uno con
    `docs/generated` se sirve como proyecto. Así un agente que trabaja en el repo A puede
    consultar la documentación del repo B con el mismo servidor, sin cambiar de configuración.
    """

    root: Path = Path(".")
    docs_dir: Path = Path("docs/generated")
    manifest_path: Path | None = None
    profile_path: Path | None = None
    workspace: Path | None = None
    dense: bool = True
    _refs: dict[str, ProjectRef] = field(default_factory=dict, init=False, repr=False)
    _indexes: dict[str, DocIndex] = field(default_factory=dict, init=False, repr=False)
    _code_indexes: dict[str, object] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        root_ref = ProjectRef(name=self.root.name, root=self.root, docs_dir=self.docs_dir)
        self._refs = {}
        # En modo workspace solo se sirve la raíz si tiene documentación: la carpeta contenedora
        # no es un proyecto, y listarla confunde al agente que elige destino.
        if self.workspace is None or root_ref.has_docs:
            self._refs[root_ref.name] = root_ref
        if self.workspace is not None:
            for ref in discover_workspace(self.workspace):
                self._refs.setdefault(ref.name, ref)

    # ------------------------------------------------------------------ proyectos

    def projects(self) -> list[ProjectRef]:
        """Proyectos servidos: la raíz del servidor y los descubiertos en el workspace."""
        return list(self._refs.values())

    def resolve(self, arguments: Mapping[str, Any]) -> ProjectRef:
        """Proyecto solicitado; si hay uno solo, no hace falta nombrarlo."""
        requested = str(arguments.get("project") or "").strip()
        candidates = self.projects()
        if requested:
            for ref in candidates:
                if ref.name == requested:
                    return ref
            names = ", ".join(sorted(ref.name for ref in candidates)) or "ninguno"
            raise ToolError(f"proyecto desconocido: {requested!r} (disponibles: {names})")
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise ToolError(
                "no hay proyectos documentados; ejecuta `docu gen` en el proyecto "
                "o apunta el servidor a un workspace con documentación"
            )
        names = ", ".join(sorted(ref.name for ref in candidates)) or "ninguno"
        raise ToolError(f"hay varios proyectos: indica 'project' ({names})")

    def _index_for(self, ref: ProjectRef) -> DocIndex:
        index = self._indexes.get(ref.name)
        if index is None:
            index = DocIndex.from_directory(ref.docs_dir, glossary=self._glossary(ref))
            self._indexes[ref.name] = index
        return index

    @property
    def index(self) -> DocIndex:
        """Indice del proyecto raíz (o del primero disponible si la raíz no está documentada)."""
        ref = self._refs.get(self.root.name)
        if ref is None:
            candidates = self.projects()
            if not candidates:
                raise ToolError("no hay proyectos documentados")
            ref = candidates[0]
        return self._index_for(ref)


    def _glossary(self, ref: ProjectRef) -> Mapping[str, Sequence[str]] | None:
        """Glosario por defecto + el del perfil: el MCP responde con el vocabulario del proyecto.

        El perfil puede estar **fuera** del repositorio (por ejemplo, si se generó la documentación
        sin escribir nada dentro del proyecto): se acepta explícitamente con `--profile`.
        """
        from docu.core.profile import find, load
        from docu.retrieve.glossary import DEFAULT_GLOSSARY, merge

        path = self.profile_path or find(ref.root)
        if path is None:
            return None
        profile = load(path, fallback_project=ref.root.name)
        if profile is None or not profile.glossary:
            return None
        return merge(DEFAULT_GLOSSARY, profile.glossary)


    def _require_docs(self, ref: ProjectRef) -> DocIndex:
        index = self._index_for(ref)
        if index.is_empty:
            raise ToolError(
                f"no hay documentación generada para {ref.name!r} en {ref.docs_dir}; "
                f"ejecuta `docu gen --root {ref.root} --out {ref.docs_dir}`"
            )
        return index

    # ------------------------------------------------------------------ herramientas

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if name not in READ_ONLY_TOOLS:
            raise ToolError(f"herramienta desconocida: {name}")
        handler = getattr(self, f"_tool_{name}")
        return handler(dict(arguments))

    def _tool_list_projects(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        del arguments
        return {
            "projects": [
                {
                    "name": ref.name,
                    "root": str(ref.root),
                    "docs_dir": str(ref.docs_dir),
                    "documented": ref.has_docs,
                }
                for ref in self.projects()
            ],
            "total": len(self.projects()),
        }

    def _tool_search_code(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Recuperación sobre el código: tres canales fusionados, con citas de línea."""
        from docu.retrieve.hybrid import build_index

        ref = self.resolve(arguments)
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ToolError("'query' es obligatorio")
        limit = max(1, min(int(arguments.get("limit") or 8), 20))
        index = self._code_indexes.get(ref.name)
        if index is None:
            index = build_index(ref.root, dense=self.dense, glossary=self._glossary(ref))
            self._code_indexes[ref.name] = index
        hits = index.search(query, limit=limit)  # type: ignore[attr-defined]
        if not hits:
            raise ToolError(f"sin coincidencias en el código de {ref.name!r} para {query!r}")
        return {
            "project": ref.name,
            "query": query,
            "capabilities": index.capabilities(),  # type: ignore[attr-defined]
            "results": [chunk.to_dict(score) for chunk, score in hits],
            "total": len(hits),
        }

    def _tool_search_docs(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        ref = self.resolve(arguments)
        index = self._require_docs(ref)
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ToolError("'query' es obligatorio")
        limit = int(arguments.get("limit") or 5)
        level = arguments.get("level")
        hits = index.search(query, limit=max(1, min(limit, 20)), level=str(level) if level else None)
        return {
            "project": ref.name,
            "query": query,
            "results": [
                {
                    "heading": section.heading,
                    "document": section.document,
                    "level": section.level,
                    "score": round(score, 4),
                    "citations": list(section.citations),
                    "excerpt": _excerpt(section.body),
                }
                for section, score in hits
            ],
            "total": len(hits),
        }

    def _tool_get_module(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        ref = self.resolve(arguments)
        index = self._require_docs(ref)
        name = str(arguments.get("name") or "").strip()
        if not name:
            raise ToolError("'name' es obligatorio")
        hits = index.search(name, limit=5, expand_query=False)
        if not hits:
            raise ToolError(f"sin documentación para el módulo {name!r} en {ref.name!r}")
        section, score = hits[0]
        return {
            "project": ref.name,
            "module": name,
            "heading": section.heading,
            "document": section.document,
            "score": round(score, 4),
            "citations": list(section.citations),
            "body": section.body,
        }

    def _tool_get_symbol_doc(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        ref = self.resolve(arguments)
        index = self._require_docs(ref)
        symbol = str(arguments.get("symbol") or "").strip()
        if not symbol:
            raise ToolError("'symbol' es obligatorio")
        hits = index.search(symbol, limit=5, expand_query=False)
        evidence = [
            {
                "heading": section.heading,
                "document": section.document,
                "citations": list(section.citations),
                "excerpt": _excerpt(section.body),
            }
            for section, _score in hits
        ]
        if not evidence:
            raise ToolError(f"el símbolo {symbol!r} no aparece en la documentación de {ref.name!r}")
        return {"project": ref.name, "symbol": symbol, "evidence": evidence}

    def _tool_list_gaps(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        ref = self.resolve(arguments)
        index = self._require_docs(ref)
        gaps = [
            {"document": section.document, "heading": section.heading}
            for section in index.sections
            if NO_EVIDENCE_MARKER in section.body
        ]
        return {"project": ref.name, "gaps": gaps, "total": len(gaps)}

    def _tool_get_architecture(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        ref = self.resolve(arguments)
        model = load_architecture(ref.root)
        if model.is_empty:
            raise ToolError(
                f"no hay modelo arquitectónico en {ref.name!r}; "
                "genera una foto con `docu drift --bootstrap`"
            )
        return {
            "project": ref.name,
            "sources": list(model.sources),
            "components": [
                {
                    "name": component.name,
                    "kind": component.kind,
                    "provides": [route.key for route in component.provides],
                    "depends_on": list(component.depends_on),
                }
                for component in model.components
            ],
            "routes": [route.key for route in model.routes],
        }

    def _tool_get_freshness(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        ref = self.resolve(arguments)
        manifest, states, hashes = inspect(ref.root, manifest_path=self.manifest_path)
        return {
            "project": manifest.project if manifest else ref.name,
            "generated": manifest is not None,
            "states": {level: state.value for level, state in states.items()},
            "hashes": hashes,
        }

    # ------------------------------------------------------------------ protocolo

    def handle(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        """Atiende una peticion JSON-RPC. Devuelve `None` para notificaciones."""
        identifier = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        if "id" not in request:
            return None  # notificacion: `notifications/initialized` y similares

        try:
            if method == "initialize":
                return _result(
                    identifier,
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": SERVER_NAME, "version": __version__},
                        "instructions": (
                            "Documentación técnica generada por docu. Todas las respuestas incluyen "
                            "citas `archivo#L`. El servidor es de solo lectura."
                        ),
                    },
                )
            if method == "ping":
                return _result(identifier, {})
            if method == "tools/list":
                return _result(identifier, {"tools": list(TOOL_DEFINITIONS)})
            if method == "tools/call":
                name = str(params.get("name") or "")
                arguments = params.get("arguments") or {}
                if name not in READ_ONLY_TOOLS:
                    return _error(identifier, -32602, f"herramienta no soportada: {name}")
                payload = self.call_tool(name, arguments)
                return _result(
                    identifier,
                    {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]},
                )
            return _error(identifier, -32601, f"método no soportado: {method}")
        except ToolError as error:
            return _result(
                identifier,
                {
                    "content": [{"type": "text", "text": json.dumps({"error": str(error)}, ensure_ascii=False)}],
                    "isError": True,
                },
            )
        except (ValueError, TypeError) as error:
            return _error(identifier, -32602, f"parámetros inválidos: {error}")

    def serve(self, instream: Any = None, outstream: Any = None) -> int:
        """Bucle stdio: una peticion JSON por linea, una respuesta por linea."""
        source = instream or sys.stdin
        sink = outstream or sys.stdout
        for line in source:
            text = line.strip()
            if not text:
                continue
            try:
                request = json.loads(text)
            except json.JSONDecodeError as error:
                sink.write(json.dumps(_error(None, -32700, f"JSON inválido: {error}"), ensure_ascii=False) + "\n")
                sink.flush()
                continue
            if not isinstance(request, dict):
                sink.write(json.dumps(_error(None, -32600, "se esperaba un objeto"), ensure_ascii=False) + "\n")
                sink.flush()
                continue
            response = self.handle(request)
            if response is not None:
                sink.write(json.dumps(response, ensure_ascii=False) + "\n")
                sink.flush()
        return 0


# --------------------------------------------------------------------------- utilidades


def _result(identifier: object, result: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": identifier, "result": dict(result)}


def _error(identifier: object, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}


def _excerpt(body: str, limit: int = 1200) -> str:
    text = body.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def discover_workspace(workspace: Path | str) -> list[ProjectRef]:
    """Proyectos documentados dentro de una carpeta de trabajo.

    Criterio: un subdirectorio es un proyecto servible si tiene documentación generada
    (`docs/generated/*.md`) o un manifest de frescura (`.docu/manifest.json`). Nada de adivinar
    por nombre de carpeta.
    """
    base = Path(workspace)
    if not base.exists() or not base.is_dir():
        return []
    refs: list[ProjectRef] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        generated = child / "docs" / "generated"
        docs = generated if any(generated.glob("*.md")) else None
        if docs is None and (child / ".docu" / "manifest.json").exists():
            docs = generated
        if docs is None:
            continue
        refs.append(ProjectRef(name=child.name, root=child, docs_dir=docs))
    return refs


def build_server(
    root: Path | str = ".",
    docs_dir: Path | str | None = None,
    workspace: Path | str | None = None,
    dense: bool = True,
    profile_path: Path | str | None = None,
) -> McpServer:
    root_path = Path(root)
    return McpServer(
        root=root_path,
        docs_dir=Path(docs_dir) if docs_dir else root_path / "docs" / "generated",
        workspace=Path(workspace) if workspace else None,
        dense=dense,
        profile_path=Path(profile_path) if profile_path else None,
    )


__all__ = [
    "McpServer",
    "PROTOCOL_VERSION",
    "ProjectRef",
    "READ_ONLY_TOOLS",
    "TOOL_DEFINITIONS",
    "ToolError",
    "build_server",
    "discover_workspace",
]
