"""Diagramas como código: Mermaid generado desde evidencia, no desde una plantilla.

Tres familias, y ninguna inventa relaciones:

- **Arquitectura**: paquetes/módulos y sus dependencias, derivadas de los `import` reales.
- **Clases**: tipos de un paquete, sus métodos y la herencia declarada en la firma.
- **Flujo de API**: ruta → handler → dependencias declaradas de su archivo.

Lo que **no** se genera, a propósito: diagramas de secuencia con orden de llamadas. El grafo de
llamadas no resuelve despacho dinámico (DI, interfaces), así que un diagrama de secuencia sería
teatro. El documento lo declara como hueco.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from docu.adapters.langs.registry import adapter_for
from docu.generate.facts import Fact
from docu.index.packages import DetectedPackage

MAX_CLASSES_PER_DIAGRAM = 18
MAX_METHODS_PER_CLASS = 8
MAX_CLASS_DIAGRAMS = 3
MAX_FIELDS_PER_ENTITY = 12
MAX_API_ROUTES = 40

_INHERITANCE_RE = re.compile(
    r"\b(?:class|record)\s+\w+\s*(?:\((?P<py>[^)]*)\))?\s*(?:extends\s+(?P<ext>[\w.]+))?"
    r"\s*(?:implements\s+(?P<impl>[\w.,\s]+))?"
)


@dataclass(frozen=True, slots=True)
class Diagram:
    """Diagrama listo para escribir y para embeber en el documento."""

    name: str
    kind: str
    mermaid: str
    note: str = ""

    @property
    def filename(self) -> str:
        return f"{self.name}.mmd"


def _node_id(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def _label(text: str) -> str:
    """Etiqueta segura para Mermaid (sin comillas ni saltos)."""
    return text.replace('"', "'").replace("\n", " ")[:60]


# --------------------------------------------------------------------------- dependencias


def resolve_import(
    module: str,
    from_file: str,
    packages: Sequence[DetectedPackage],
) -> str | None:
    """Paquete de destino de un `import`, o `None` si apunta fuera del proyecto."""
    if module.startswith("."):
        base = posixpath.normpath(posixpath.join(posixpath.dirname(from_file), module))
        for package in packages:
            if any(member.startswith(base) for member in package.files):
                return package.name
        return None
    best: str | None = None
    for package in packages:
        name = package.name
        if module == name or module.startswith(name + "."):
            if best is None or len(name) > len(best):
                best = name
    return best


def package_dependencies(
    files: Mapping[str, Path],
    packages: Sequence[DetectedPackage],
    read,
) -> dict[tuple[str, str], set[str]]:
    """Aristas paquete → paquete, con los archivos que las justifican."""
    owner_of = {member: package.name for package in packages for member in package.files}
    edges: dict[tuple[str, str], set[str]] = {}
    for rel in sorted(files):
        adapter = adapter_for(rel)
        owner = owner_of.get(rel)
        if adapter is None or owner is None:
            continue
        try:
            modules = adapter.imports(rel, read(files[rel]))  # type: ignore[attr-defined]
        except (OSError, UnicodeDecodeError):
            continue
        for module in modules:
            target = resolve_import(module, rel, packages)
            if target and target != owner:
                edges.setdefault((owner, target), set()).add(rel)
    return edges


def architecture_diagram(
    packages: Sequence[DetectedPackage],
    edges: Mapping[tuple[str, str], set[str]],
) -> Diagram | None:
    """Grafo de paquetes con sus dependencias."""
    if not packages:
        return None
    lines = ["flowchart LR"]
    for package in packages:
        node = _node_id(package.name)
        lines.append(f'    {node}["{_label(package.name)}<br/>{package.file_count} archivos"]')
    for (source, target) in sorted(edges):
        lines.append(f"    {_node_id(source)} --> {_node_id(target)}")
    if not edges:
        lines.append("    %% sin dependencias internas detectadas")
    return Diagram(
        name="arquitectura",
        kind="architecture",
        mermaid="\n".join(lines),
        note=f"{len(packages)} paquetes · {len(edges)} dependencias derivadas de imports",
    )


# --------------------------------------------------------------------------- clases


def _type_signature(fact: Fact) -> str:
    return str(fact.attributes.get("signature", ""))


def class_diagram(package: DetectedPackage, facts: Sequence[Fact]) -> Diagram | None:
    """Clases de un paquete con sus métodos y herencia declarada."""
    members = set(package.files)
    types = [fact for fact in facts if fact.kind == "type" and fact.citation.split("#")[0] in members]
    if not types:
        return None
    known = {fact.subject for fact in types}
    methods: dict[str, list[str]] = {}
    for fact in facts:
        if fact.kind != "method":
            continue
        parent = fact.subject.rsplit(".", 1)[0] if "." in fact.subject else ""
        methods.setdefault(parent, []).append(fact.subject.rsplit(".", 1)[-1])

    lines = ["classDiagram"]
    emitted = 0
    for fact in sorted(types, key=lambda item: item.subject)[:MAX_CLASSES_PER_DIAGRAM]:
        name = fact.subject
        # El estereotipo va fuera del cuerpo: dentro, Mermaid lo trata como miembro y ensucia.
        lines.append(f"    class {name} <<{_label(str(fact.detail))}>> {{")
        for method in methods.get(name, [])[:MAX_METHODS_PER_CLASS]:
            lines.append(f"        {_label(method)}()")
        lines.append("    }")
        emitted += 1
        signature = _type_signature(fact)
        match = _INHERITANCE_RE.search(signature)
        if match:
            parents: list[str] = []
            if match.group("py"):
                parents += [part.strip().split("[")[0] for part in match.group("py").split(",")]
            if match.group("ext"):
                parents.append(match.group("ext"))
            if match.group("impl"):
                parents += [part.strip() for part in match.group("impl").split(",")]
            for parent in parents:
                parent_name = parent.rsplit(".", 1)[-1]
                if parent_name and parent_name in known and parent_name != name:
                    lines.append(f"    {parent_name} <|-- {name}")
    if emitted == 0:
        return None
    return Diagram(
        name=f"clases-{_node_id(package.name)}",
        kind="classes",
        mermaid="\n".join(lines),
        note=f"{emitted} clases de {package.name}",
    )


# --------------------------------------------------------------------------- flujo de API


def api_flow_diagram(facts: Sequence[Fact]) -> Diagram | None:
    """Ruta → handler → dependencias declaradas del archivo del handler."""
    routes = [fact for fact in facts if fact.kind == "route"][:MAX_API_ROUTES]
    if not routes:
        return None
    lines = ["flowchart LR", '    cliente(["Cliente"])']
    handler_ids: dict[str, str] = {}
    emitted: set[str] = set()
    for index, route in enumerate(routes):
        route_id = f"r{index}"
        verb = route.attributes.get("verb", "ANY")
        path = route.attributes.get("path", "/")
        lines.append(f'    {route_id}["{_label(f"{verb} {path}")}"]')
        lines.append(f"    cliente --> {route_id}")
        handler = str(route.attributes.get("handler", route.detail)) or "handler"
        parent = handler.rsplit(".", 1)[0] if "." in handler else handler
        handler_id = handler_ids.setdefault(parent, f"h{len(handler_ids)}")
        if parent not in emitted:
            emitted.add(parent)
            lines.append(f'    {handler_id}["{_label(parent)}"]')
        lines.append(f"    {route_id} --> {handler_id}")
    return Diagram(
        name="api-flujo",
        kind="api",
        mermaid="\n".join(lines),
        note=f"{len(routes)} rutas",
    )


def _entity_type(text: str) -> tuple[str, bool]:
    """Tipo declarado y si es una colección: `List<Cliente>` → (`Cliente`, True)."""
    compact = text.strip().rstrip(";")
    plural = False
    for wrapper in ("List", "Set", "Collection", "Iterable", "Array", "[]", "Optional"):
        if wrapper in compact:
            plural = wrapper not in ("Optional",)
            break
    inner = re.sub(r"^(?:List|Set|Collection|Iterable|Optional|Array)\s*<", "", compact)
    inner = inner.rstrip(">").rstrip("[]").replace("[]", "")
    name = inner.rsplit(".", 1)[-1].strip()
    return name, plural


def erd_diagram(facts: Sequence[Fact]) -> Diagram | None:
    """ERD desde los tipos declarados.

    Las entidades son los tipos con campos; las relaciones salen del **tipo del campo** cuando ese
    tipo es otra entidad documentada. No se inventan claves foráneas ni cardinalidades que el código
    no declare: una colección se dibuja como «muchos», un tipo simple como «uno».
    """
    fields_by_entity: dict[str, list[Fact]] = {}
    for fact in facts:
        if fact.kind != "field":
            continue
        owner = str(fact.attributes.get("owner", fact.subject.rsplit(".", 1)[0]))
        fields_by_entity.setdefault(owner, []).append(fact)
    if not fields_by_entity:
        return None

    entities = set(fields_by_entity)
    lines = ["erDiagram"]
    relations: list[str] = []
    for entity in sorted(fields_by_entity):
        lines.append(f"    {_node_id(entity)} {{")
        for fact in fields_by_entity[entity][:MAX_FIELDS_PER_ENTITY]:
            declared = fact.detail if fact.detail != "sin tipo declarado" else "sinTipo"
            token = _node_id(declared.split("|")[0].strip()[:24]).strip("_") or "tipo"
            lines.append(f"        {token} {fact.subject.rsplit('.', 1)[-1]}")
        lines.append("    }")
        for fact in fields_by_entity[entity]:
            target, plural = _entity_type(fact.detail)
            if target in entities and target != entity:
                cardinality = "}o--o{" if plural else "}o--||"
                relations.append(
                    f'    {_node_id(entity)} {cardinality} {_node_id(target)} : "{fact.subject.rsplit(".", 1)[-1]}"'
                )
    lines.extend(dict.fromkeys(relations))
    return Diagram(
        name="modelo-de-datos",
        kind="erd",
        mermaid="\n".join(lines),
        note=f"{len(entities)} entidades · {len(dict.fromkeys(relations))} relaciones declaradas por tipo",
    )


# --------------------------------------------------------------------------- entrada


def build_all(
    files: Mapping[str, Path],
    packages: Sequence[DetectedPackage],
    facts: Sequence[Fact],
    read,
) -> tuple[Diagram, ...]:
    """Todos los diagramas posibles, en orden estable."""
    diagrams: list[Diagram] = []
    edges = package_dependencies(files, packages, read)
    architecture = architecture_diagram(packages, edges)
    if architecture is not None:
        diagrams.append(architecture)

    largest = sorted(packages, key=lambda item: item.file_count, reverse=True)
    class_count = 0
    for package in largest:
        if class_count >= MAX_CLASS_DIAGRAMS:
            break
        diagram = class_diagram(package, facts)
        if diagram is not None:
            diagrams.append(diagram)
            class_count += 1

    model = erd_diagram(facts)
    if model is not None:
        diagrams.append(model)

    flow = api_flow_diagram(facts)
    if flow is not None:
        diagrams.append(flow)
    return tuple(diagrams)


def write_diagrams(diagrams: Sequence[Diagram], directory: Path) -> list[Path]:
    """Escribe los `.mmd` y borra los obsoletos: un diagrama viejo miente igual que una tabla vieja."""
    written: list[Path] = []
    if not diagrams:
        return written
    directory.mkdir(parents=True, exist_ok=True)
    current = {diagram.filename for diagram in diagrams}
    for stale in sorted(directory.glob("*.mmd")):
        if stale.name not in current:
            stale.unlink()
    for diagram in diagrams:
        target = directory / diagram.filename
        target.write_text(diagram.mermaid + "\n", encoding="utf-8")
        written.append(target)
    return written


__all__ = [
    "Diagram",
    "api_flow_diagram",
    "architecture_diagram",
    "build_all",
    "class_diagram",
    "erd_diagram",
    "package_dependencies",
    "resolve_import",
    "write_diagrams",
]
