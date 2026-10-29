"""Adaptador Python sobre `ast` de la libreria estandar.

Sin dependencias y con informacion que un regex no da: decoradores reales, funciones anidadas,
`async`, firmas con valores por defecto y rutas de FastAPI/Flask.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from docu.core.contracts import Symbol, SymbolKind

HTTP_VERBS = frozenset({"get", "post", "put", "delete", "patch", "route", "head", "options"})
HTTP_DECORATORS = frozenset({"route", "get", "post", "put", "delete", "patch", "head", "options", "api_route"})


@dataclass(frozen=True, slots=True)
class PythonLangAdapter:
    """`LangAdapter` para Python. Devuelve `()` ante codigo invalido en lugar de reventar."""

    language: str = "python"
    file_globs: tuple[str, ...] = ("*.py",)

    # ------------------------------------------------------------------ simbolos

    def symbols(self, path: str, source: str) -> tuple[Symbol, ...]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return ()

        found: list[Symbol] = []
        for node in tree.body:
            symbol = self._module_member(path, node, container=None)
            if symbol is not None:
                found.append(symbol)
            found.extend(self._routes(path, node, container=None))
        return tuple(found)

    def _module_member(
        self, path: str, node: ast.AST, container: str | None
    ) -> Symbol | None:
        if isinstance(node, ast.ClassDef):
            children = tuple(
                child
                for child in (
                    self._module_member(path, item, container=node.name) for item in node.body
                )
                if child is not None
            )
            fields = tuple(
                field
                for field in (
                    self._class_field(path, item, container=node.name) for item in node.body
                )
                if field is not None
            )
            return Symbol(
                name=node.name,
                qualname=node.name if container is None else f"{container}.{node.name}",
                kind=SymbolKind.CLASS,
                path=path,
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", node.lineno),
                signature=f"class {node.name}({', '.join(_base_name(base) for base in node.bases)})",
                children=fields + children,
                annotations=self._decorators(node),
            )
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return Symbol(
                name=node.name,
                qualname=node.name if container is None else f"{container}.{node.name}",
                kind=SymbolKind.METHOD if container else SymbolKind.FUNCTION,
                path=path,
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", node.lineno),
                signature=_signature(node),
                annotations=self._decorators(node),
            )
        return None

    def _class_field(self, path: str, node: ast.AST, container: str) -> Symbol | None:
        """Campo de clase: `nombre: Tipo` (anotado) o `nombre = valor` (sin tipo).

        Los tipos declarados son la materia prima del diccionario de datos y del ERD: sin ellos el
        documento describe métodos pero no datos, que es la mitad de una integración.
        """
        if isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name):
                return None
            annotation = ast.unparse(node.annotation)
            return Symbol(
                name=node.target.id,
                qualname=f"{container}.{node.target.id}",
                kind=SymbolKind.FIELD,
                path=path,
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", node.lineno),
                signature=annotation,
                annotations=(),
            )
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if len(names) != 1 or names[0].isupper():  # constantes de módulo: no son entidades
                return None
            return Symbol(
                name=names[0],
                qualname=f"{container}.{names[0]}",
                kind=SymbolKind.FIELD,
                path=path,
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", node.lineno),
                signature="",
                annotations=(),
            )
        return None

    def _decorators(self, node: ast.AST) -> tuple[str, ...]:
        decorators = getattr(node, "decorator_list", ())
        return tuple(f"@{_decorator_name(item)}" for item in decorators)

    def _routes(self, path: str, node: ast.AST, container: str | None) -> list[Symbol]:
        """Rutas HTTP declaradas por decorador (FastAPI/Flask)."""
        routes: list[Symbol] = []
        for decorator in getattr(node, "decorator_list", ()):
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            name = _decorator_name(target)
            short = name.rsplit(".", 1)[-1].lower()
            if short not in HTTP_DECORATORS:
                continue
            verb, route = _route_of(short, decorator)
            if route is None:
                continue
            qualname = node.name if container is None else f"{container}.{node.name}"
            routes.append(
                Symbol(
                    name=f"{verb} {route}",
                    qualname=qualname,
                    kind=SymbolKind.HTTP_ROUTE,
                    path=path,
                    line_start=getattr(decorator, "lineno", node.lineno),
                    line_end=getattr(node, "lineno", getattr(decorator, "lineno", 0)),
                    signature=_signature(node) if isinstance(node, ast.AST) else "",
                    annotations=(f"@{name}",),
                )
            )
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                routes.extend(self._routes(path, item, container=node.name))
        return routes

    # ------------------------------------------------------------------ imports y llamadas

    def imports(self, path: str, source: str) -> tuple[str, ...]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return ()
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
        return tuple(dict.fromkeys(modules))

    def calls(self, path: str, source: str) -> tuple[tuple[str, str], ...]:
        """Aristas (llamador, llamado) entre funciones declaradas en el mismo archivo.

        Se atribuye la llamada a la funcion **mas interna** que la contiene; sin resolucion de
        tipos, atribuirla a otra cosa produciria aristas falsas.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return ()
        functions = _function_table(tree)
        by_short: dict[str, list[str]] = {}
        for qualname, _start, _end in functions:
            by_short.setdefault(qualname.rsplit(".", 1)[-1], []).append(qualname)
        edges: list[tuple[str, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = _call_name(node.func)
            if not callee or callee not in by_short:
                continue
            # Se prefiere el nombre calificado cuando es unico: `service.create()` es
            # `OrderService.create`, no `create`.
            resolved = by_short[callee][0] if len(by_short[callee]) == 1 else callee
            line = getattr(node, "lineno", 0)
            candidates = sorted(
                (end - start, qualname)
                for qualname, start, end in functions
                if start <= line <= end and qualname != resolved
            )
            if candidates:
                edges.append((candidates[0][1], resolved))
        return tuple(dict.fromkeys(edges))


# --------------------------------------------------------------------------- utilidades


def _base_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_base_name(node.value)}.{node.attr}"
    return "?"


def _decorator_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    if isinstance(node, ast.Attribute):
        return f"{_decorator_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    return "?"


def _route_of(short: str, decorator: ast.AST) -> tuple[str, str | None]:
    """(verbo, ruta) desde el decorador, incluido `methods=[...]` de Flask."""
    verb = short.upper() if short != "route" else "ANY"
    route: str | None = None
    if isinstance(decorator, ast.Call):
        for argument in decorator.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                route = argument.value
                break
        for keyword in decorator.keywords:
            if keyword.arg == "path" and isinstance(keyword.value, ast.Constant):
                route = keyword.value.value
            if keyword.arg == "methods" and isinstance(keyword.value, ast.List):
                methods = [
                    element.value
                    for element in keyword.value.elts
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)
                ]
                if methods:
                    verb = methods[0].upper()
    return verb, route


def _signature(node: ast.AST) -> str:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return ""
    args = node.args
    parts: list[str] = []
    positional = [*args.posonlyargs, *args.args]
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for argument, default in zip(positional, defaults):
        annotation = f": {ast.unparse(argument.annotation)}" if argument.annotation else ""
        suffix = "=..." if default is not None else ""
        parts.append(f"{argument.arg}{annotation}{suffix}")
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({', '.join(parts)}){returns}"


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _function_table(tree: ast.AST) -> list[tuple[str, int, int]]:
    """(nombre calificado, linea inicio, linea fin) de cada funcion, con su clase contenedora."""
    table: list[tuple[str, int, int]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                visit(child, f"{prefix}.{node.name}" if prefix else node.name)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = f"{prefix}.{node.name}" if prefix else node.name
            table.append((qualname, node.lineno, getattr(node, "end_lineno", node.lineno)))
            for child in node.body:
                visit(child, qualname)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, prefix)

    visit(tree, "")
    return table
