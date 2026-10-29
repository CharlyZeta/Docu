"""Modelo arquitectonico prescriptivo: arquitectura como codigo.

Se leen dos fuentes de verdad *declarada*: el modelo de componentes (YAML/JSON propio, compatible
con el estilo C4InterFlow) y los contratos OpenAPI. Lo que no este declarado no se inventa: se
reporta como deriva.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from docu.core.yamlmini import YamlError, parse

ARCHITECTURE_CANDIDATES = (
    "architecture.yaml",
    "architecture.yml",
    "architecture.json",
    "docs/architecture.yaml",
    "docs/architecture.yml",
    "infra/architecture.yaml",
    "infra/architecture.yml",
)
OPENAPI_CANDIDATES = ("openapi.yaml", "openapi.yml", "openapi.json", "api/openapi.yaml", "docs/openapi.yaml")
HTTP_METHODS = ("get", "post", "put", "delete", "patch", "head", "options")


@dataclass(frozen=True, slots=True)
class Route:
    verb: str
    path: str

    @property
    def key(self) -> str:
        return f"{self.verb.upper()} {self.path}"

    def __str__(self) -> str:
        return self.key


@dataclass(frozen=True, slots=True)
class DeclaredComponent:
    name: str
    kind: str = "component"
    provides: tuple[Route, ...] = ()
    depends_on: tuple[str, ...] = ()
    source: str = ""


@dataclass(frozen=True, slots=True)
class ArchitectureModel:
    components: tuple[DeclaredComponent, ...] = ()
    routes: tuple[Route, ...] = ()
    sources: tuple[str, ...] = ()
    schema_version: str = "1.0"

    @property
    def component_names(self) -> set[str]:
        return {component.name for component in self.components}

    @property
    def declared_routes(self) -> set[str]:
        returns = {route.key for route in self.routes}
        for component in self.components:
            returns.update(route.key for route in component.provides)
        return returns

    def declared_dependencies(self) -> set[tuple[str, str]]:
        return {
            (component.name, dependency)
            for component in self.components
            for dependency in component.depends_on
        }

    @property
    def is_empty(self) -> bool:
        return not self.components and not self.routes


# --------------------------------------------------------------------------- carga


def _read_document(path: Path) -> Mapping[str, object] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        if path.suffix == ".json":
            payload = json.loads(text)
        else:
            payload = parse(text)
    except (json.JSONDecodeError, YamlError):
        return None
    return payload if isinstance(payload, dict) else None


def load_architecture(root: Path, explicit: Path | str | None = None) -> ArchitectureModel:
    """Carga el modelo declarado. Devuelve un modelo vacio si no hay artefactos."""
    root = Path(root)
    sources: list[str] = []
    components: list[DeclaredComponent] = []
    routes: list[Route] = []

    candidates = [Path(explicit)] if explicit else [root / name for name in ARCHITECTURE_CANDIDATES]
    for candidate in candidates:
        if not candidate.exists():
            continue
        document = _read_document(candidate)
        if document is None:
            continue
        relative = candidate.relative_to(root).as_posix() if candidate.is_relative_to(root) else str(candidate)
        sources.append(relative)
        architecture = document.get("architecture")
        block = architecture if isinstance(architecture, dict) else document
        components.extend(_components_from(block, relative))

    for name in OPENAPI_CANDIDATES:
        candidate = root / name
        if not candidate.exists():
            continue
        document = _read_document(candidate)
        if document is None:
            continue
        relative = candidate.relative_to(root).as_posix()
        sources.append(relative)
        routes.extend(_routes_from_openapi(document))

    return ArchitectureModel(
        components=tuple(components),
        routes=tuple(routes),
        sources=tuple(dict.fromkeys(sources)),
    )


def _components_from(block: Mapping[str, object], source: str) -> list[DeclaredComponent]:
    raw = block.get("components")
    if not isinstance(raw, list):
        return []
    components: list[DeclaredComponent] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        provides = tuple(_route_from_text(str(entry)) for entry in _as_list(item.get("provides")))
        components.append(
            DeclaredComponent(
                name=name,
                kind=str(item.get("kind") or "component"),
                provides=tuple(route for route in provides if route is not None),
                depends_on=tuple(str(entry) for entry in _as_list(item.get("depends_on"))),
                source=source,
            )
        )
    return components


def _routes_from_openapi(document: Mapping[str, object]) -> list[Route]:
    paths = document.get("paths")
    if not isinstance(paths, dict):
        return []
    routes: list[Route] = []
    for path, operations in paths.items():
        if not isinstance(operations, dict):
            continue
        for method in operations:
            if str(method).lower() in HTTP_METHODS:
                routes.append(Route(verb=str(method).upper(), path=str(path)))
    return routes


def _as_list(value: object) -> Iterable[object]:
    if value is None:
        return ()
    if isinstance(value, list):
        return value
    return (value,)


def _route_from_text(text: str) -> Route | None:
    """`"POST /api/x"` → `Route`. Ignora entradas que no son rutas."""
    parts = text.strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    verb, path = parts
    if verb.upper() not in {method.upper() for method in HTTP_METHODS}:
        return None
    return Route(verb=verb.upper(), path=path)


def to_yaml(model: ArchitectureModel, project: str) -> str:
    """Serializa el modelo en el formato prescriptivo que el propio agente sabe releer."""
    lines = [
        "# Modelo arquitectonico prescriptivo generado por docu.",
        "# Editarlo es decidir: el agente compara este archivo con el codigo real y reporta deriva.",
        "architecture:",
        f"  project: {project}",
        "  components:",
    ]
    for component in model.components:
        lines.append(f"    - name: {component.name}")
        lines.append(f"      kind: {component.kind}")
        if component.provides:
            provided = ", ".join(f'"{route.key}"' for route in component.provides)
            lines.append(f"      provides: [{provided}]")
        else:
            lines.append("      provides: []")
        if component.depends_on:
            lines.append(f"      depends_on: [{', '.join(component.depends_on)}]")
        else:
            lines.append("      depends_on: []")
    if not model.components:
        lines.append("    []")
    return "\n".join(lines) + "\n"


__all__ = [
    "ArchitectureModel",
    "DeclaredComponent",
    "Route",
    "load_architecture",
    "to_yaml",
]
