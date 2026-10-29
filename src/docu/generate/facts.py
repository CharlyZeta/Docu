"""Extraccion de hechos verificables desde los artefactos.

Principio del producto: **un hecho sin cita no es un hecho**, es una opinion. Cada `Fact` que
sale de aqui apunta a un archivo y a un rango de lineas. Si un extractor no puede citar, no
emite el hecho: el documento mostrara el hueco declarado en lugar de inventar prosa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from docu.core.contracts import Symbol, SymbolKind

JAVA_SUFFIX = ".java"
YAML_SUFFIXES = (".yml", ".yaml")
POM_NAME = "pom.xml"

_YAML_LINE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_.\-]+)\s*:\s*(?P<value>.*)$")
_POM_DEPENDENCY = re.compile(r"<dependency>(?P<body>.*?)</dependency>", re.DOTALL)
_POM_MODULE = re.compile(r"<module>(?P<name>[^<]+)</module>")
_POM_PLUGIN = re.compile(r"<plugin>(?P<body>.*?)</plugin>", re.DOTALL)
_POM_TAG = r"<{tag}>\s*(?P<value>[^<]+?)\s*</{tag}>"
_COMMENT = re.compile(r"(^|\s)#.*$")


@dataclass(frozen=True, slots=True)
class Fact:
    """Una afirmacion atomica con su evidencia."""

    kind: str
    subject: str
    detail: str
    citation: str
    attributes: Mapping[str, str] = field(default_factory=dict)

    @property
    def verified(self) -> bool:
        return bool(self.citation)

    @property
    def location(self) -> str:
        return self.citation


def _line_of(text: str, offset: int) -> int:
    return text[:offset].count("\n") + 1


def _tag_value(body: str, tag: str) -> str | None:
    match = re.search(_POM_TAG.format(tag=tag), body, re.DOTALL)
    return match.group("value").strip() if match else None


# --------------------------------------------------------------------------- Java


def symbol_facts(symbols: Sequence[Symbol]) -> list[Fact]:
    """Tipos, funciones, metodos y rutas HTTP con su ubicacion exacta.

    Vale para cualquier lenguaje: los adaptadores solo tienen que devolver `Symbol`s. Una
    funcion de modulo (Python, TS) es tan documentable como un metodo de clase.
    """
    facts: list[Fact] = []
    for symbol in symbols:
        citation = f"{symbol.path}#L{symbol.line_start}-L{symbol.line_end}"
        if symbol.kind in (SymbolKind.CLASS, SymbolKind.INTERFACE, SymbolKind.ENUM):
            facts.append(
                Fact(
                    kind="type",
                    subject=symbol.name,
                    detail=symbol.kind.value,
                    citation=citation,
                    attributes={
                        "annotations": " ".join(symbol.annotations) or "—",
                        "signature": symbol.signature or "",
                    },
                )
            )
            for child in symbol.children:
                child_citation = f"{child.path}#L{child.line_start}-L{child.line_end}"
                facts.append(
                    Fact(
                        kind="method",
                        subject=child.qualname,
                        detail=child.signature or "",
                        citation=child_citation,
                        attributes={"annotations": " ".join(child.annotations) or "—"},
                    )
                )
        elif symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD, SymbolKind.CONSTRUCTOR):
            facts.append(
                Fact(
                    kind="method",
                    subject=symbol.qualname,
                    detail=symbol.signature or "",
                    citation=citation,
                    attributes={"annotations": " ".join(symbol.annotations) or "—"},
                )
            )
        elif symbol.kind is SymbolKind.HTTP_ROUTE:
            verb, _, route = symbol.name.partition(" ")
            facts.append(
                Fact(
                    kind="route",
                    subject=symbol.name,
                    detail=symbol.qualname,
                    citation=citation,
                    attributes={"verb": verb, "path": route, "handler": symbol.qualname},
                )
            )
    return facts


#: Alias historico: el extractor nacio para Java y hoy sirve a cualquier `LangAdapter`.
java_facts = symbol_facts


# --------------------------------------------------------------------------- YAML


def yaml_facts(path: str, source: str) -> list[Fact]:
    """Claves aplanadas (`a.b.c`) con su linea. Parser de subconjunto, no un YAML completo."""
    facts: list[Fact] = []
    stack: list[tuple[int, str]] = []
    for index, raw in enumerate(source.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        match = _YAML_LINE.match(raw)
        if not match:
            continue
        indent = len(match.group("indent").expandtabs(2))
        key = match.group("key")
        value = _COMMENT.sub("", match.group("value")).strip().strip('"').strip("'")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        prefix = ".".join([parent for _level, parent in stack])
        dotted = f"{prefix}.{key}" if prefix else key
        if value:
            facts.append(
                Fact(
                    kind="config_key",
                    subject=dotted,
                    detail=value,
                    citation=f"{path}#L{index}-L{index}",
                    attributes={"key": dotted, "value": value},
                )
            )
        else:
            stack.append((indent, key))
    return facts


# --------------------------------------------------------------------------- Maven


def pom_facts(path: str, source: str) -> list[Fact]:
    """Modules, propiedades del parent y dependencias declaradas, con linea exacta."""
    facts: list[Fact] = []
    for match in _POM_MODULE.finditer(source):
        name = match.group("name").strip()
        line = _line_of(source, match.start())
        facts.append(
            Fact(
                kind="module",
                subject=name,
                detail="módulo de build",
                citation=f"{path}#L{line}-L{line}",
                attributes={"module": name},
            )
        )

    for tag in ("java.version", "spring-security.version", "jjwt.version"):
        for match in re.finditer(_POM_TAG.format(tag=re.escape(tag)), source, re.DOTALL):
            line = _line_of(source, match.start())
            facts.append(
                Fact(
                    kind="property",
                    subject=tag,
                    detail=match.group("value").strip(),
                    citation=f"{path}#L{line}-L{line}",
                    attributes={"property": tag, "value": match.group("value").strip()},
                )
            )

    for match in _POM_DEPENDENCY.finditer(source):
        body = match.group("body")
        group = _tag_value(body, "groupId")
        artifact = _tag_value(body, "artifactId")
        if not group or not artifact:
            continue
        version = _tag_value(body, "version") or "(gestionada por el parent)"
        scope = _tag_value(body, "scope") or "compile"
        line = _line_of(source, match.start() + body.find("<artifactId>"))
        facts.append(
            Fact(
                kind="dependency",
                subject=f"{group}:{artifact}",
                detail=version,
                citation=f"{path}#L{line}-L{line}",
                attributes={"group": group, "artifact": artifact, "version": version, "scope": scope},
            )
        )

    for match in _POM_PLUGIN.finditer(source):
        artifact = _tag_value(match.group("body"), "artifactId")
        if not artifact:
            continue
        line = _line_of(source, match.start())
        facts.append(
            Fact(
                kind="plugin",
                subject=artifact,
                detail="plugin de build",
                citation=f"{path}#L{line}-L{line}",
                attributes={"artifact": artifact},
            )
        )

    parent = re.search(r"<parent>(?P<body>.*?)</parent>", source, re.DOTALL)
    if parent:
        body = parent.group("body")
        artifact = _tag_value(body, "artifactId")
        version = _tag_value(body, "version")
        if artifact and version:
            line = _line_of(source, parent.start())
            facts.append(
                Fact(
                    kind="parent",
                    subject=artifact,
                    detail=version,
                    citation=f"{path}#L{line}-L{line}",
                    attributes={"artifact": artifact, "version": version},
                )
            )
    return facts


# --------------------------------------------------------------------------- dependencias no Maven


def _line_with(text: str, needle: str) -> int:
    """Linea de la primera aparicion del texto, o 1 si no aparece (nunca miente la cita)."""
    index = text.find(needle)
    return text[: index].count("\n") + 1 if index >= 0 else 1


def _line_with_after(text: str, needle: str, start: int) -> int:
    """Linea de la primera aparicion **a partir de** `start`, con retroceso a la primera global."""
    index = text.find(needle, max(0, start))
    if index < 0:
        index = text.find(needle)
    return text[: index].count("\n") + 1 if index >= 0 else 1


def requirements_facts(path: str, source: str) -> list[Fact]:
    """`requirements.txt`: una dependencia por linea, con su version si la fija."""
    facts: list[Fact] = []
    for index, raw in enumerate(source.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, _, version = line.partition("==")
        facts.append(
            Fact(
                kind="dependency",
                subject=name.strip(),
                detail=version.strip() or "(sin versión fija)",
                citation=f"{path}#L{index}-L{index}",
                attributes={"scope": "runtime", "version": version.strip()},
            )
        )
    return facts


def package_json_facts(path: str, source: str) -> list[Fact]:
    """`package.json`: dependencias y devDependencies con la linea del nombre."""
    import json

    try:
        payload = json.loads(source)
    except json.JSONDecodeError:
        return []
    facts: list[Fact] = []
    for scope, key in (("runtime", "dependencies"), ("dev", "devDependencies")):
        block = payload.get(key) or {}
        # `vite` puede estar en dependencies y en devDependencies: buscar desde la seccion evita
        # citar siempre la primera aparicion y crear duplicados falsos.
        section_start = source.find(f'"{key}"')
        for name, version in block.items():
            line = _line_with_after(source, f'"{name}"', section_start)
            facts.append(
                Fact(
                    kind="dependency",
                    subject=name,
                    detail=str(version),
                    citation=f"{path}#L{line}-L{line}",
                    attributes={"scope": scope, "version": str(version)},
                )
            )
    return facts


def pyproject_facts(path: str, source: str) -> list[Fact]:
    """`pyproject.toml`: dependencias de `[project]` y de sus extras, y la versión de Python exigida.

    Leer solo `dependencies` deja fuera a la mitad del ecosistema Python: `optional-dependencies`
    es donde vive casi todo (framework web, linters, base de datos). Omitirlo produce manuales que
    afirman «este proyecto no tiene dependencias» sobre un proyecto que sí las tiene.
    """
    import tomllib

    try:
        payload = tomllib.loads(source)
    except tomllib.TOMLDecodeError:
        return []
    project = payload.get("project") or {}
    facts: list[Fact] = []
    requires = project.get("requires-python")
    if requires:
        line = _line_with(source, "requires-python")
        facts.append(
            Fact(
                kind="property",
                subject="requires-python",
                detail=str(requires),
                citation=f"{path}#L{line}-L{line}",
                attributes={"property": "requires-python", "value": str(requires)},
            )
        )

    groups: list[tuple[str, object]] = [("runtime", project.get("dependencies") or [])]
    extras = project.get("optional-dependencies") or {}
    if isinstance(extras, dict):
        groups.extend((str(name), requirements) for name, requirements in extras.items())

    for scope, requirements in groups:
        if not isinstance(requirements, list):
            continue
        for requirement in requirements:
            name = re.split(r"[<>=!~\[ ]", str(requirement), maxsplit=1)[0].strip()
            if not name:
                continue
            version = str(requirement)[len(name) :] or "(sin versión fija)"
            line = _line_with(source, str(requirement))
            facts.append(
                Fact(
                    kind="dependency",
                    subject=name,
                    detail=version,
                    citation=f"{path}#L{line}-L{line}",
                    attributes={"scope": scope, "version": version},
                )
            )
    return facts


def package_facts(packages: Sequence[object]) -> list[Fact]:
    """Unidades arquitectonicas detectadas: paquetes Python, paquetes Java, barriles TypeScript."""
    facts: list[Fact] = []
    for package in packages:
        name = str(getattr(package, "name", ""))
        if not name:
            continue
        language = str(getattr(package, "language", "desconocido"))
        files = int(getattr(package, "file_count", 0))
        facts.append(
            Fact(
                kind="package",
                subject=name,
                detail=f"{files} archivos · {language}",
                citation=str(getattr(package, "citation", "")),
                attributes={"language": language, "files": str(files)},
            )
        )
    return facts


# --------------------------------------------------------------------------- verificacion


def unsupported(facts: Sequence[Fact]) -> list[Fact]:
    """Hechos que no se pueden sostener: la compuerta dura del producto."""
    return [fact for fact in facts if not fact.verified]
