"""Adaptador Java sin dependencias externas (implementacion de referencia de F1).

Por que no `tree-sitter` todavia: el contrato del puerto `LangAdapter` es lo que importa y el
entorno de F1 no tiene el paquete instalado. Este parser es **estructural** (mascara comentarios
y literales, empareja llaves, mide profundidad) y suficiente para lo que el producto necesita en
Java: tipos, metodos, anotaciones, imports y rutas HTTP de Spring.

Limite declarado y respetado: no hay resolucion de tipos. El despacho dinamico, los genericos
complejos y la inyeccion de dependencias no se infieren ni se inventan: se omiten. Cuando
`tree-sitter-java` este disponible, sustituye a este modulo sin tocar `core/`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from docu.adapters.langs._braces import (
    annotations_before,
    iter_callables,
    mask_annotation_braces,
    matching_paren,
)
from docu.core.contracts import Symbol, SymbolKind

CONTROL_WORDS = frozenset(
    "if for while switch catch return new throw do else try synchronized assert yield".split()
)

#: Palabras que preceden a una declaracion de tipo, no a un metodo: `record X(...)`, `new X(...)`.
NOT_METHODS = frozenset("record class interface enum new return extends implements throws".split())

#: Modificadores que no forman parte del tipo de un campo.
FIELD_MODIFIERS = frozenset(
    "public private protected static final transient volatile readonly default".split()
)

HTTP_MAPPINGS = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
    "RequestMapping": None,  # el verbo va en el argumento (RequestMethod.X)
}

_TYPE_RE = re.compile(r"\b(class|interface|enum|record)\s+([A-Za-z_]\w*)")
_METHOD_RE = re.compile(
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^()]*)\)\s*(?:throws\s+[\w.,\s]+?)?(?P<tail>[{;])"
)
_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)(\.\*)?\s*;", re.MULTILINE)
_ANNOTATION_RE = re.compile(r"^\s*@([A-Za-z_]\w*)(?:\(([^()]*)\))?", re.MULTILINE)
_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_CALL_RE = re.compile(r"(?:\.\s*)?([A-Za-z_]\w*)\s*\(")


# --------------------------------------------------------------------------- utilidades


def mask_source(source: str) -> str:
    """Sustituye comentarios y literales por espacios, conservando saltos de linea.

    Sin esto, una llave dentro de un string o de un comentario desalinea todo el analisis.
    """
    out = list(source)
    i, n = 0, len(source)
    while i < n:
        ch = source[i]
        if ch == "/" and i + 1 < n and source[i + 1] == "/":
            while i < n and source[i] != "\n":
                out[i] = " "
                i += 1
        elif ch == "/" and i + 1 < n and source[i + 1] == "*":
            out[i] = out[i + 1] = " "
            i += 2
            while i < n and not (source[i] == "*" and i + 1 < n and source[i + 1] == "/"):
                if source[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = " "
                if i + 1 < n:
                    out[i + 1] = " "
                i += 2
        elif source.startswith('"""', i):
            out[i] = out[i + 1] = out[i + 2] = " "
            i += 3
            while i < n and not source.startswith('"""', i):
                if source[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = out[i + 1] = out[i + 2] = " "
                i += 3
        elif ch in ('"', "'"):
            quote = ch
            out[i] = " "
            i += 1
            while i < n:
                if source[i] == "\\":
                    out[i] = " "
                    if i + 1 < n:
                        out[i + 1] = " "
                    i += 2
                    continue
                if source[i] == quote:
                    out[i] = " "
                    i += 1
                    break
                if source[i] != "\n":
                    out[i] = " "
                i += 1
        else:
            i += 1
    return "".join(out)


def depth_map(masked: str) -> list[int]:
    """`depth[i]` = llaves abiertas antes de la posicion `i`."""
    depth = [0] * len(masked)
    current = 0
    for index, ch in enumerate(masked):
        depth[index] = current
        if ch == "{":
            current += 1
        elif ch == "}":
            current -= 1
    return depth


def matching_brace(masked: str, open_index: int) -> int:
    """Indice de la llave de cierre correspondiente (o el final si esta desbalanceado)."""
    level = 0
    for index in range(open_index, len(masked)):
        ch = masked[index]
        if ch == "{":
            level += 1
        elif ch == "}":
            level -= 1
            if level == 0:
                return index
    return len(masked) - 1


class _Lines:
    """Conversion offsets <-> numeros de linea (1-based)."""

    def __init__(self, source: str) -> None:
        self.starts = [0]
        for index, ch in enumerate(source):
            if ch == "\n":
                self.starts.append(index + 1)

    def line_of(self, offset: int) -> int:
        low, high = 0, len(self.starts) - 1
        while low < high:
            mid = (low + high + 1) // 2
            if self.starts[mid] <= offset:
                low = mid
            else:
                high = mid - 1
        return low + 1


def annotation_names(text: str) -> tuple[str, ...]:
    """Nombres de anotacion (`@Service`), sin argumentos."""
    return tuple(f"@{name}" for name, _args in _ANNOTATION_RE.findall(text))


def route_of(annotation: str, args: str | None) -> tuple[str, str | None] | None:
    """(verbo, ruta) si la anotacion es de Spring MVC; `None` en caso contrario."""
    if annotation not in HTTP_MAPPINGS:
        return None
    literal: str | None = None
    if args:
        found = _STRING_RE.search(args)
        literal = found.group(1) if found else None
    verb = HTTP_MAPPINGS[annotation]
    if verb is None:
        explicit = re.search(r"RequestMethod\.([A-Z]+)", args or "")
        verb = explicit.group(1) if explicit else "ANY"
    return verb, literal


def class_level_route(text: str) -> str | None:
    """Ruta base declarada con `@RequestMapping` a nivel de tipo."""
    for annotation, args in _ANNOTATION_RE.findall(text):
        mapping = route_of(annotation, args)
        if mapping and mapping[1]:
            return mapping[1]
    return None


def join_paths(base: str | None, suffix: str | None) -> str:
    """Une base y ruta y normaliza a una ruta HTTP con barra inicial."""
    if not base:
        combined = suffix or "/"
    elif not suffix:
        combined = base
    else:
        combined = base.rstrip("/") + "/" + suffix.lstrip("/")
    return "/" + combined.lstrip("/")


def _strip_annotations(text: str) -> str:
    return _ANNOTATION_RE.sub(" ", text)


def _java_fields(
    masked: str,
    source: str,
    depth: list[int],
    level: int,
    open_brace: int,
    close_brace: int,
    type_name: str,
    path: str,
    lines: "_Lines",
) -> list[Symbol]:
    """Campos declarados en el cuerpo del tipo.

    Sin campos no hay diccionario de datos ni ERD: el documento podía decir «qué métodos tiene»
    pero no «qué datos guarda», que es la mitad de lo que un equipo necesita para integrarse.
    """
    fields: list[Symbol] = []
    boundary = open_brace + 1
    index = open_brace + 1
    while index < close_brace:
        char = masked[index]
        if char == "{" and depth[index] == level - 1:
            # Bloque anidado (tipo interno, inicializador o cuerpo de método): se salta entero.
            index = matching_brace(masked, index) + 1
            boundary = index
            continue
        if char == ";" and depth[index] == level:
            statement = masked[boundary:index]
            raw = source[boundary:index]
            boundary = index + 1
            cleaned = " ".join(_strip_annotations(statement).split())
            if not cleaned or "(" in cleaned.split("=", 1)[0]:
                index += 1
                continue
            head = cleaned.split("=", 1)[0].strip()
            tokens = [token for token in head.split() if token not in FIELD_MODIFIERS]
            if len(tokens) < 2:
                index += 1
                continue
            name = tokens[-1]
            if not name.replace("_", "").isalnum() or not name[:1].isalpha():
                index += 1
                continue
            field_type = " ".join(tokens[:-1])
            name_offset = source.rfind(name, boundary - len(raw) - 1, index + 1)
            field_line = lines.line_of(name_offset if name_offset != -1 else boundary)
            fields.append(
                Symbol(
                    name=name,
                    qualname=f"{type_name}.{name}",
                    kind=SymbolKind.FIELD,
                    path=path,
                    line_start=field_line,
                    line_end=lines.line_of(index),
                    signature=field_type,
                    annotations=annotation_names(raw),
                )
            )
        index += 1
    return fields


def _record_fields(
    masked: str,
    source: str,
    type_name: str,
    path: str,
    match_end: int,
    lines: "_Lines",
) -> list[Symbol]:
    """Componentes de un `record`: son sus campos, aunque vivan en la firma."""
    paren = masked.find("(", match_end)
    if paren == -1:
        return []
    close = matching_paren(masked, paren)
    body = source[paren + 1 : close]
    fields: list[Symbol] = []
    depth = 0
    chunk: list[str] = []
    for char in body + ",":
        if char in "(<[":
            depth += 1
        elif char in ")>]":
            depth -= 1
        if char == "," and depth == 0:
            component = " ".join("".join(chunk).split())
            chunk = []
            if not component:
                continue
            cleaned = _strip_annotations(component)
            tokens = [token for token in cleaned.split() if token not in FIELD_MODIFIERS]
            if len(tokens) < 2:
                continue
            name = tokens[-1]
            line = lines.line_of(source.find(name, paren))
            fields.append(
                Symbol(
                    name=name,
                    qualname=f"{type_name}.{name}",
                    kind=SymbolKind.FIELD,
                    path=path,
                    line_start=line,
                    line_end=line,
                    signature=" ".join(tokens[:-1]),
                    annotations=annotation_names(component),
                )
            )
            continue
        chunk.append(char)
    return fields


def _annotation_block(source: str, start: int, end: int) -> tuple[str, int]:
    """Anotaciones entre dos posiciones y offset donde empieza la primera.

    Se toma el tramo completo entre el final del miembro anterior y el nombre actual: es
    deterministico y evita adivinar donde acaba un bloque multilinea como
    `@ApiResponses(value = { ... })`.
    """
    segment = source[start:end]
    position = segment.find("@")
    if position < 0:
        return "", end
    return segment[position:], start + position


def _declaration_start(masked: str, depth: list[int], offset: int, floor: int, level: int) -> int:
    """Inicio de la declaracion que contiene `offset`.

    Reglas de frontera, y el detalle que importa: la llave `{` que abre un metodo anterior
    tiene la **misma** profundidad que el miembro actual, pero no es su inicio. La frontera
    real es el `}` de cierre de ese miembro previo, que vive una profundidad mas adentro.
    """
    index = offset - 1
    while index > floor:
        ch = masked[index]
        if depth[index] == level and ch == ";":
            return _skip_whitespace(masked, index + 1, offset)
        if depth[index] == level + 1 and ch == "}":
            return _skip_whitespace(masked, index + 1, offset)
        if depth[index] == level and ch == "}":
            break
        index -= 1
    return _skip_whitespace(masked, floor, offset)


def _skip_whitespace(text: str, start: int, limit: int) -> int:
    """Avanza sobre espacios y saltos: la declaracion empieza en la primera anotacion o token."""
    index = start
    while index < limit and text[index].isspace():
        index += 1
    return index


# --------------------------------------------------------------------------- adaptador


@dataclass(frozen=True, slots=True)
class JavaLangAdapter:
    """`LangAdapter` de referencia. Sin estado: seguro para procesar archivos en paralelo."""

    language: str = "java"
    file_globs: tuple[str, ...] = ("*.java",)

    # ------------------------------------------------------------------ simbolos

    def symbols(self, path: str, source: str) -> tuple[Symbol, ...]:
        masked = mask_annotation_braces(mask_source(source))
        depth = depth_map(masked)
        lines = _Lines(source)
        routes: list[Symbol] = []
        types: list[tuple[Symbol, int, int]] = []  # (simbolo, offset inicio, offset fin)
        previous_end = 0

        for match in _TYPE_RE.finditer(masked):
            keyword, name = match.group(1), match.group(2)
            if masked[max(0, match.start() - 1)] == ".":
                continue  # `Foo.class` no es una declaracion
            open_brace = masked.find("{", match.end())
            if open_brace == -1:
                continue
            close_brace = matching_brace(masked, open_brace)
            level = depth[open_brace]
            decl_start = _declaration_start(masked, depth, match.start(), 0, level)
            annotation_text, annotation_offset = _annotation_block(source, previous_end, match.start())
            annotations = annotation_names(annotation_text)
            base_route = class_level_route(annotation_text)
            type_line = lines.line_of(decl_start)
            if annotation_text:
                type_line = min(type_line, lines.line_of(annotation_offset))
            previous_end = close_brace + 1

            children, member_routes = self._members(
                path=path,
                source=source,
                masked=masked,
                depth=depth,
                lines=lines,
                level=level + 1,
                open_brace=open_brace,
                close_brace=close_brace,
                type_name=name,
                base_route=base_route,
            )
            fields = _java_fields(
                masked,
                source,
                depth,
                level + 1,
                open_brace,
                close_brace,
                name,
                path,
                lines,
            )
            if keyword == "record":
                fields = _record_fields(masked, source, name, path, match.end(), lines) or fields
            children = fields + children
            routes.extend(member_routes)

            type_kind = {
                "class": SymbolKind.CLASS,
                "interface": SymbolKind.INTERFACE,
                "enum": SymbolKind.ENUM,
                "record": SymbolKind.CLASS,
            }[keyword]

            # Un tipo anidado pertenece a su contenedor, no al conjunto de tipos del archivo:
            # si se lista como hermano, el documento de arquitectura miente sobre la jerarquia.
            parent_index = None
            for index, (_symbol, start, end) in enumerate(types):
                if start < decl_start and close_brace < end:
                    if parent_index is None or start > types[parent_index][1]:
                        parent_index = index

            symbol = Symbol(
                name=name,
                qualname=name,
                kind=type_kind,
                path=path,
                line_start=max(1, type_line),
                line_end=lines.line_of(close_brace),
                signature=" ".join(source[decl_start:open_brace].split())[:300],
                children=tuple(children),
                annotations=annotations,
            )
            if parent_index is None:
                types.append((symbol, decl_start, close_brace))
            else:
                parent, start, end = types[parent_index]
                nested = replace(symbol, qualname=f"{parent.qualname}.{name}")
                types[parent_index] = (
                    replace(parent, children=(*parent.children, nested)),
                    start,
                    end,
                )

        found = [symbol for symbol, _start, _end in types] + routes
        return tuple(sorted(found, key=lambda item: (item.line_start, item.qualname)))

    def _members(
        self,
        *,
        path: str,
        source: str,
        masked: str,
        depth: list[int],
        lines: _Lines,
        level: int,
        open_brace: int,
        close_brace: int,
        type_name: str,
        base_route: str | None,
    ) -> tuple[list[Symbol], list[Symbol]]:
        members: list[Symbol] = []
        routes: list[Symbol] = []
        previous_end = open_brace + 1
        for name, paren_open, _paren_close, tail_index in iter_callables(
            masked, depth, level, open_brace + 1, close_brace, CONTROL_WORDS
        ):
            if masked[tail_index] == ";":
                continue  # firma sin cuerpo: no es un metodo documentable

            # Inicio del nombre: retroceder sobre espacios desde el parentesis de apertura.
            cursor = paren_open - 1
            while cursor > open_brace and masked[cursor].isspace():
                cursor -= 1
            name_start = cursor - len(name) + 1

            # `record Request(...)` o `new Thing(...)` no son metodos: la palabra previa lo dice.
            word_end = name_start - 1
            while word_end > open_brace and masked[word_end].isspace():
                word_end -= 1
            word_start = word_end
            while word_start > open_brace and (masked[word_start].isalnum() or masked[word_start] in "_$"):
                word_start -= 1
            if masked[word_start + 1 : word_end + 1] in NOT_METHODS:
                # Saltar el bloque completo para que la proxima anotacion no herede estas lineas.
                previous_end = (
                    matching_brace(masked, tail_index) + 1 if masked[tail_index] == "{" else tail_index + 1
                )
                continue

            decl_start = _declaration_start(masked, depth, name_start, open_brace + 1, level)
            if decl_start <= open_brace:
                continue

            body_close = matching_brace(masked, tail_index)
            annotation_text, annotation_offset = _annotation_block(source, previous_end, name_start)
            previous_end = body_close + 1
            annotations = annotation_names(annotation_text)
            line_start = lines.line_of(decl_start)
            if annotation_text:
                line_start = min(line_start, lines.line_of(annotation_offset))
            signature = " ".join(source[decl_start:tail_index].split())[:300]

            members.append(
                Symbol(
                    name=name,
                    qualname=f"{type_name}.{name}",
                    kind=SymbolKind.CONSTRUCTOR if name == type_name else SymbolKind.METHOD,
                    path=path,
                    line_start=line_start,
                    line_end=lines.line_of(body_close),
                    signature=signature,
                    annotations=annotations,
                )
            )

            for annotation, args in _ANNOTATION_RE.findall(annotation_text):
                mapping = route_of(annotation, args)
                if mapping is None:
                    continue
                verb, route_path = mapping
                routes.append(
                    Symbol(
                        name=f"{verb} {join_paths(base_route, route_path)}",
                        qualname=f"{type_name}.{name}",
                        kind=SymbolKind.HTTP_ROUTE,
                        path=path,
                        line_start=line_start,
                        line_end=lines.line_of(tail_index),
                        signature=signature,
                        annotations=(f"@{annotation}",),
                    )
                )
        return members, routes

    # ------------------------------------------------------------------ imports y llamadas

    def imports(self, path: str, source: str) -> tuple[str, ...]:
        masked = mask_source(source)
        return tuple(fqn for fqn, _star in _IMPORT_RE.findall(masked))

    def calls(self, path: str, source: str) -> tuple[tuple[str, str], ...]:
        """Aristas (llamador, llamado) solo entre metodos declarados en el mismo archivo.

        Cota deliberada: sin resolucion de tipos, atribuir llamadas a otros archivos produciria
        aristas falsas y diagramas que mienten.
        """
        masked = mask_source(source)
        declared: set[str] = set()
        for symbol in self.symbols(path, source):
            if symbol.kind is SymbolKind.METHOD:
                declared.add(symbol.name)
            for child in symbol.children:
                if child.kind is SymbolKind.METHOD:
                    declared.add(child.name)
        edges: list[tuple[str, str]] = []
        for match in _TYPE_RE.finditer(masked):
            open_brace = masked.find("{", match.end())
            if open_brace == -1:
                continue
            close_brace = matching_brace(masked, open_brace)
            type_name = match.group(2)
            for call in _CALL_RE.finditer(masked, open_brace, close_brace):
                callee = call.group(1)
                if callee in declared and callee != type_name:
                    edges.append((type_name, callee))
        return tuple(dict.fromkeys(edges))
