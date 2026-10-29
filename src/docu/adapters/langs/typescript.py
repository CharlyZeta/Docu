"""Adaptador TypeScript/JavaScript sobre analisis estructural (llaves + decoradores).

Cubre lo que un proyecto NestJS o Angular expone como contrato: clases, interfaces, enums,
metodos, decoradores de ruta y funciones de modulo. No resuelve tipos ni `import()` dinamico:
esas aristas no se inventan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from docu.adapters.langs._braces import (
    Lines,
    annotations_before,
    declaration_start,
    depth_map,
    iter_callables,
    mask_annotation_braces,
    mask_source,
    matching_brace,
)
from docu.core.contracts import Symbol, SymbolKind

CONTROL_WORDS = frozenset(
    "if for while switch catch return new throw do else try typeof yield await constructor".split()
)

#: Palabras que preceden a una declaracion de tipo o instanciacion, no a un metodo.
NOT_METHODS = frozenset("new class interface enum extends implements typeof function".split())

HTTP_DECORATORS = {
    "Get": "GET",
    "Post": "POST",
    "Put": "PUT",
    "Delete": "DELETE",
    "Patch": "PATCH",
    "Options": "OPTIONS",
    "Head": "HEAD",
    "All": "ANY",
}

_TYPE_RE = re.compile(r"\b(class|interface|enum)\s+([A-Za-z_$][\w$]*)")
_METHOD_RE = re.compile(
    r"(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^<>()]*>)?\s*\((?P<params>[^()]*)\)\s*"
    r"(?::\s*[^{;=]+)?\s*(?P<tail>[{;])"
)
_ARROW_RE = re.compile(
    r"(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\((?P<params>[^()]*)\)\s*"
    r"(?::\s*[^=]+)?=>"
)
_TOP_ARROW_RE = re.compile(
    r"\b(?:export\s+)?const\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?"
    r"(?:\([^()]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=>"
)
_FUNCTION_RE = re.compile(
    r"\b(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
    r"\((?P<params>[^()]*)\)"
)
_IMPORT_RE = re.compile(r"^\s*import\s+(?:type\s+)?(?:[^'\"]+\s+from\s+)?['\"](?P<module>[^'\"]+)['\"]", re.MULTILINE)
_DECORATOR_RE = re.compile(r"@([A-Za-z_$][\w$.]*)\s*(?:\(([^()]*)\))?")
_STRING_RE = re.compile(r"['\"]([^'\"]*)['\"]")
#: Rutas declaradas al estilo Express/Connect: `app.get('/api/x', handler)`.
EXPRESS_ROUTE_RE = re.compile(
    r"\b(?:app|router|server|api|fastify)\s*\.\s*(?P<verb>get|post|put|patch|delete|all|use)\s*\(\s*"
)
#: Rutas declaradas con comparaciones sobre la ruta (`pathname === '/api/x'`).
HANDROLLED_ROUTE_RE = re.compile(
    r"\b(?:pathname|path|url)\s*(?:===|==|!==|startsWith)\s*\(?\s*"
)
METHOD_IN_CONDITION_RE = re.compile(r"method\s*===?\s*['\"](\w+)['\"]")

#: Propiedad declarada (`name: string;`), también en interfaces.
#: El inicializador se separa con `=(?!>)` para no cortar los tipos función (`() => void`).
PROPERTY_RE = re.compile(
    r"(?m)^[ \t]*(?:(?:public|private|protected|readonly|static|declare|abstract)\s+)*"
    r"(?P<name>[A-Za-z_$][\w$]*)(?P<optional>\?)?\s*:\s*(?P<type>[^;\n]+?)"
    r"(?:\s*=(?!>)[^;]*)?;"
)

#: Literales que son tipos de JavaScript, no rutas (`typeof path === 'string'`).
TYPE_LITERALS = frozenset(
    "string number object boolean function undefined symbol bigint".split()
)


@dataclass(frozen=True, slots=True)
class TypeScriptLangAdapter:
    language: str = "typescript"
    file_globs: tuple[str, ...] = ("*.ts", "*.tsx", "*.js", "*.jsx")

    # ------------------------------------------------------------------ simbolos

    def symbols(self, path: str, source: str) -> tuple[Symbol, ...]:
        masked = mask_annotation_braces(mask_source(source))
        depth = depth_map(masked)
        lines = Lines(source)
        found: list[Symbol] = []
        previous_end = 0

        for match in _TYPE_RE.finditer(masked):
            open_brace = masked.find("{", match.end())
            if open_brace == -1:
                continue
            close_brace = matching_brace(masked, open_brace)
            level = depth[open_brace]
            decl_start = declaration_start(masked, depth, match.start(), 0, level)
            kind = {
                "class": SymbolKind.CLASS,
                "interface": SymbolKind.INTERFACE,
                "enum": SymbolKind.ENUM,
            }[match.group(1)]
            annotation_text, annotation_offset = _annotation_block(source, previous_end, match.start())
            annotations = _decorators_in(annotation_text)
            previous_end = close_brace + 1
            type_line = lines.line_of(decl_start)
            if annotation_text:
                type_line = min(type_line, lines.line_of(annotation_offset))

            children, routes = self._members(
                path=path,
                source=source,
                masked=masked,
                depth=depth,
                lines=lines,
                level=level + 1,
                open_brace=open_brace,
                close_brace=close_brace,
                type_name=match.group(2),
                base_route=_class_route(annotations),
            )
            found.extend(routes)
            found.append(
                Symbol(
                    name=match.group(2),
                    qualname=match.group(2),
                    kind=kind,
                    path=path,
                    line_start=max(1, type_line),
                    line_end=lines.line_of(close_brace),
                    signature=" ".join(source[decl_start:open_brace].split())[:300],
                    children=tuple(children),
                    annotations=annotations,
                )
            )

        for match in _FUNCTION_RE.finditer(masked):
            if depth[match.start()] != 0:
                continue
            decl_start = declaration_start(masked, depth, match.start(), 0, 0)
            body = masked.find("{", match.end())
            close = matching_brace(masked, body) if body != -1 else match.end()
            found.append(
                Symbol(
                    name=match.group("name"),
                    qualname=match.group("name"),
                    kind=SymbolKind.FUNCTION,
                    path=path,
                    line_start=lines.line_of(decl_start),
                    line_end=lines.line_of(close),
                    signature=" ".join(source[decl_start:match.end()].split())[:300],
                    annotations=(),
                )
            )

        for match in _TOP_ARROW_RE.finditer(masked):
            if depth[match.start()] != 0:
                continue
            body = masked.find("{", match.end())
            semicolon = masked.find(";", match.end())
            if body != -1 and (semicolon == -1 or body < semicolon):
                close = matching_brace(masked, body)
            else:
                close = semicolon if semicolon != -1 else match.end()
            found.append(
                Symbol(
                    name=match.group("name"),
                    qualname=match.group("name"),
                    kind=SymbolKind.FUNCTION,
                    path=path,
                    line_start=lines.line_of(match.start()),
                    line_end=lines.line_of(close),
                    signature=" ".join(source[match.start() : match.end()].split())[:300],
                    annotations=(),
                )
            )

        found.extend(self._express_routes(path, source, masked, lines))

        return tuple(sorted(found, key=lambda item: (item.line_start, item.qualname)))

    def _members(
        self,
        *,
        path: str,
        source: str,
        masked: str,
        depth: list[int],
        lines: Lines,
        level: int,
        open_brace: int,
        close_brace: int,
        type_name: str,
        base_route: str | None,
    ) -> tuple[list[Symbol], list[Symbol]]:
        members: list[Symbol] = []
        routes: list[Symbol] = []
        previous_end = open_brace + 1
        seen: set[str] = set()

        for name, paren_open, _paren_close, tail_index in iter_callables(
            masked, depth, level, open_brace + 1, close_brace, CONTROL_WORDS
        ):
            if masked[tail_index] == ";":
                continue  # firma sin cuerpo
            cursor = paren_open - 1
            while cursor > open_brace and masked[cursor].isspace():
                cursor -= 1
            name_start = cursor - len(name) + 1

            # `new Foo(` o `interface Foo(` no son metodos.
            word_end = name_start - 1
            while word_end > open_brace and masked[word_end].isspace():
                word_end -= 1
            word_start = word_end
            while word_start > open_brace and (masked[word_start].isalnum() or masked[word_start] in "_$"):
                word_start -= 1
            if masked[word_start + 1 : word_end + 1] in NOT_METHODS:
                previous_end = (
                    matching_brace(masked, tail_index) + 1 if masked[tail_index] == "{" else tail_index + 1
                )
                continue

            decl_start = declaration_start(masked, depth, name_start, open_brace + 1, level)
            if decl_start <= open_brace:
                continue
            body_close = matching_brace(masked, tail_index)
            annotation_text, annotation_offset = _annotation_block(source, previous_end, name_start)
            previous_end = body_close + 1
            annotations = _decorators_in(annotation_text)
            signature = " ".join(source[decl_start:tail_index].split())[:300]
            line_start = lines.line_of(decl_start)
            if annotation_text:
                line_start = min(line_start, lines.line_of(annotation_offset))
            seen.add(name)
            members.append(
                Symbol(
                    name=name,
                    qualname=f"{type_name}.{name}",
                    kind=SymbolKind.METHOD,
                    path=path,
                    line_start=line_start,
                    line_end=lines.line_of(body_close),
                    signature=signature,
                    annotations=annotations,
                )
            )
            for annotation in annotations:
                verb = HTTP_DECORATORS.get(annotation.lstrip("@").split("(")[0])
                if not verb:
                    continue
                route = _route_path(annotation_text, annotation)
                routes.append(
                    Symbol(
                        name=f"{verb} {_join(base_route, route)}",
                        qualname=f"{type_name}.{name}",
                        kind=SymbolKind.HTTP_ROUTE,
                        path=path,
                        line_start=line_start,
                        line_end=lines.line_of(tail_index),
                        signature=signature,
                        annotations=(annotation,),
                    )
                )

        # Propiedades con funcion flecha: mismo tratamiento, otro detector.
        for match in _ARROW_RE.finditer(masked, open_brace + 1, close_brace):
            name = match.group("name")
            if name in seen or depth[match.start()] != level:
                continue
            decl_start = declaration_start(masked, depth, match.start(), open_brace + 1, level)
            if decl_start <= open_brace:
                continue
            body = masked.find("{", match.end())
            close = matching_brace(masked, body) if body != -1 else match.end()
            annotation_text, annotation_offset = _annotation_block(source, previous_end, decl_start)
            annotations = _decorators_in(annotation_text)
            line_start = lines.line_of(decl_start)
            if annotation_text:
                line_start = min(line_start, lines.line_of(annotation_offset))
            seen.add(name)
            members.append(
                Symbol(
                    name=name,
                    qualname=f"{type_name}.{name}",
                    kind=SymbolKind.METHOD,
                    path=path,
                    line_start=line_start,
                    line_end=lines.line_of(close),
                    signature=" ".join(source[decl_start:match.end()].split())[:300],
                    annotations=annotations,
                )
            )

        # Propiedades declaradas: materia prima del diccionario de datos y del ERD.
        for match in PROPERTY_RE.finditer(masked, open_brace + 1, close_brace):
            if depth[match.start()] != level:
                continue
            name = match.group("name")
            if name in seen:
                continue
            seen.add(name)
            members.append(
                Symbol(
                    name=name,
                    qualname=f"{type_name}.{name}",
                    kind=SymbolKind.FIELD,
                    path=path,
                    line_start=lines.line_of(match.start()),
                    line_end=lines.line_of(match.end()),
                    signature=" ".join(match.group("type").split())
                    + (" | ausente" if match.group("optional") else ""),
                    annotations=(),
                )
            )
        return members, routes

    def _express_routes(self, path: str, source: str, masked: str, lines: Lines) -> list[Symbol]:
        """Rutas declaradas por llamada (`app.get('/x', ...)`) o por comparación de ruta.

        Segunda forma, muy común en servidores Node sin framework: `if (pathname === '/api/x' &&
        req.method === 'GET')`. Se detecta el literal y el verbo del mismo `if`; si no hay verbo,
        la ruta se documenta como `ANY`. Es una inferencia: el `handler` lo dice.
        """
        routes: list[Symbol] = []
        seen: set[tuple[str, str]] = set()

        # Se busca sobre el texto original (hacen falta los literales) y se descarta lo que cae
        # dentro de comentarios o cadenas comprobando que el identificador sigue visible en el
        # texto enmascarado.
        def is_code(position: int) -> bool:
            return position < len(masked) and masked[position] == source[position]

        for match in EXPRESS_ROUTE_RE.finditer(source):
            if not is_code(match.start()):
                continue
            literal = _STRING_RE.match(source, match.end())
            if literal is None:
                continue
            verb = match.group("verb").upper()
            if verb == "USE":
                verb = "ANY"
            route = "/" + literal.group(1).lstrip("/")
            if (verb, route) in seen:
                continue
            seen.add((verb, route))
            line = lines.line_of(match.start())
            routes.append(
                Symbol(
                    name=f"{verb} {route}",
                    qualname=f"{match.group('verb')}({route})",
                    kind=SymbolKind.HTTP_ROUTE,
                    path=path,
                    line_start=line,
                    line_end=line,
                    signature=match.group(0).strip() + literal.group(0),
                    annotations=(),
                )
            )

        for match in HANDROLLED_ROUTE_RE.finditer(source):
            if not is_code(match.start()):
                continue
            # `typeof path === 'string'` no es una ruta: se descarta el tipo y el operador typeof.
            before = source[max(0, match.start() - 12) : match.start()]
            if "typeof" in before:
                continue
            literal = _STRING_RE.match(source, match.end())
            if literal is None:
                continue
            if literal.group(1).lower() in TYPE_LITERALS:
                continue
            route = "/" + literal.group(1).lstrip("/")
            if len(route) < 4 or route.endswith("/"):
                continue
            line_end = source.find("\n", match.end())
            window = source[match.start() : (line_end if line_end != -1 else len(source)) + 200]
            verb_match = METHOD_IN_CONDITION_RE.search(window)
            verb = verb_match.group(1).upper() if verb_match else "ANY"
            if (verb, route) in seen:
                continue
            seen.add((verb, route))
            line = lines.line_of(match.start())
            routes.append(
                Symbol(
                    name=f"{verb} {route}",
                    qualname="comparación de pathname",
                    kind=SymbolKind.HTTP_ROUTE,
                    path=path,
                    line_start=line,
                    line_end=line,
                    signature=f"if ({match.group(0).strip()}{literal.group(0)} …)",
                    annotations=(),
                )
            )
        return routes

    def imports(self, path: str, source: str) -> tuple[str, ...]:
        return tuple(match.group("module") for match in _IMPORT_RE.finditer(source))

    def calls(self, path: str, source: str) -> tuple[tuple[str, str], ...]:
        """Aristas entre funciones o metodos declarados en el mismo archivo."""
        symbols = self.symbols(path, source)
        declared = {symbol.name for symbol in symbols if symbol.kind in (SymbolKind.METHOD, SymbolKind.FUNCTION)}
        edges: list[tuple[str, str]] = []
        for symbol in symbols:
            for child in symbol.children:
                body = source.splitlines()[child.line_start - 1 : child.line_end]
                for line in body:
                    for name in re.findall(r"[A-Za-z_$][\w$]*\s*\(", line):
                        callee = name.rstrip("(").strip()
                        if callee in declared and callee != child.name:
                            edges.append((child.name, callee))
        return tuple(dict.fromkeys(edges))


# --------------------------------------------------------------------------- utilidades


def _annotation_block(source: str, start: int, end: int) -> tuple[str, int]:
    """Decoradores entre dos posiciones y offset del primero."""
    segment = source[start:end]
    position = segment.find("@")
    if position < 0:
        return "", end
    return segment[position:], start + position


def _decorators_in(text: str) -> tuple[str, ...]:
    """Expresiones de decorador completas, con sus argumentos y sin saltos de linea."""
    found = [" ".join(match.group(0).split()) for match in _DECORATOR_RE.finditer(text)]
    return tuple(dict.fromkeys(found))


def _class_route(decorators: tuple[str, ...]) -> str | None:
    for decorator in decorators:
        if decorator.lstrip("@").startswith("Controller"):
            found = _STRING_RE.search(decorator)
            return found.group(1) if found else ""
    return None


def _route_path(text: str, annotation: str) -> str:
    name = annotation.lstrip("@").split("(")[0]
    pattern = re.compile(r"@" + re.escape(name) + r"\s*\(([^()]*)\)")
    match = pattern.search(text)
    if not match:
        return "/"
    literal = _STRING_RE.search(match.group(1))
    return literal.group(1) if literal else "/"


def _join(base: str | None, route: str) -> str:
    """Une base y ruta y normaliza a una ruta HTTP con barra inicial."""
    if route in ("", "/"):
        combined = base or "/"
    elif not base:
        combined = route
    else:
        combined = base.rstrip("/") + "/" + route.lstrip("/")
    return "/" + combined.lstrip("/")
