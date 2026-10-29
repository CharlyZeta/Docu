"""Utilidades compartidas de analisis estructural para lenguajes con llaves.

Vive aparte para que Java y TypeScript no se importen entre si: si un adaptador depende de otro,
el "agnosticismo por puertos" es decorativo.
"""

from __future__ import annotations

import re


def mask_source(source: str, *, template_literals: bool = True) -> str:
    """Sustituye comentarios y literales por espacios, conservando los saltos de linea.

    Sin esto, una llave dentro de un string o un template literal desalinea todo el analisis.
    """
    out = list(source)
    i, n = 0, len(source)
    quotes = '"\'`' if template_literals else '"\''
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
        elif ch in quotes:
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


def mask_annotation_braces(masked: str) -> str:
    """Anula las llaves que viven **dentro** de una anotacion.

    `@ApiResponses(value = { @ApiResponse(...), ... })` usa llaves de Java real: si se dejan, el
    conteo de profundidad cree que hay un bloque y todos los metodos posteriores quedan «dentro» de
    la anotacion, con lo que se pierden el metodo y su ruta. FastAPI/NestJS no lo necesitan, pero
    dañar el conteo cuesta caro; anular es barato.
    """
    out = list(masked)
    index = 0
    total = len(masked)
    while index < total:
        if masked[index] == "@":
            cursor = index + 1
            while cursor < total and (masked[cursor].isalnum() or masked[cursor] in "_."):
                cursor += 1
            while cursor < total and masked[cursor].isspace():
                cursor += 1
            if cursor < total and masked[cursor] == "(":
                close = matching_paren(masked, cursor)
                for position in range(cursor, close):
                    if out[position] in "{}":
                        out[position] = " "
                index = close + 1
                continue
        index += 1
    return "".join(out)


def matching_paren(masked: str, open_index: int) -> int:
    """Indice del parentesis de cierre correspondiente."""
    level = 0
    for index in range(open_index, len(masked)):
        ch = masked[index]
        if ch == "(":
            level += 1
        elif ch == ")":
            level -= 1
            if level == 0:
                return index
    return len(masked) - 1


def iter_callables(
    masked: str,
    depth: list[int],
    level: int,
    start: int,
    end: int,
    skip: frozenset[str] | set[str] | tuple[str, ...] = (),
):
    """Recorre declaraciones `nombre(...) {` con **parentesis balanceados**.

    Un regex `[^()]*` no sirve para Java ni TypeScript reales: los parametros llevan anotaciones
    (`@RequestHeader(value = "X", required = false)`, `@Body() dto`) y sus parentesis anidados
    rompen el patron, con lo que se pierde el metodo **y su ruta**. Aqui se camina el texto contando
    parentesis, que es lo que hace cualquier parser de verdad.
    """
    skipset = set(skip)
    index = start
    while index < end:
        if masked[index] != "(":
            index += 1
            continue
        cursor = index - 1
        while cursor >= start and masked[cursor].isspace():
            cursor -= 1
        name_end = cursor
        while cursor >= start and (masked[cursor].isalnum() or masked[cursor] in "_$"):
            cursor -= 1
        name = masked[cursor + 1 : name_end + 1]
        previous = masked[cursor] if cursor >= start else ""
        if (
            name
            and name[0].isalpha()
            and name not in skipset
            and previous != "@"
            and depth[index] == level
        ):
            close = matching_paren(masked, index)
            tail = close + 1
            while tail < end and masked[tail].isspace():
                tail += 1
            if masked.startswith("throws", tail):
                while tail < end and masked[tail] not in "{;":
                    tail += 1
            if tail < end and masked[tail] in "{;":
                yield name, index, close, tail
                index = tail + 1
                continue
            # TypeScript declara el tipo de retorno entre `)` y `{`: `: Promise<Order> {`.
            # Sin saltarlo se pierde el metodo (y su decorador de ruta).
            if tail < end and masked[tail] == ":":
                probe = tail + 1
                while probe < end and (
                    masked[probe].isalnum()
                    or masked[probe] in "_$.<>[]|&?,: \t\r\n"
                ):
                    probe += 1
                if probe < end and masked[probe] in "{;":
                    yield name, index, close, probe
                    index = probe + 1
                    continue
        index += 1


def annotations_before(source: str, name_start: int) -> str:
    """Bloque de anotaciones inmediatamente encima de una declaracion.

    Se lee hacia arriba por lineas y se aceptan continuaciones mientras queden parentesis o llaves
    abiertas. `@ApiResponses(value = { ... })` ocupa varias lineas y contiene llaves: cortar en la
    primera linea perderia tambien `@PostMapping` y, con el, la ruta.
    """
    lines = source.splitlines()
    row = source.count("\n", 0, name_start) - 1
    collected: list[str] = []
    balance = 0
    while row >= 0:
        stripped = lines[row].strip()
        if not stripped:
            if balance > 0:
                collected.append("")
                row -= 1
                continue
            break
        if balance > 0 or stripped.startswith("@"):
            collected.append(stripped)
            balance += stripped.count("(") + stripped.count("{")
            balance -= stripped.count(")") + stripped.count("}")
            row -= 1
            continue
        break
    return "\n".join(reversed(collected))


class Lines:
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


def skip_whitespace(text: str, start: int, limit: int) -> int:
    """Avanza sobre espacios y saltos: la declaracion empieza en la primera anotacion o token."""
    index = start
    while index < limit and text[index].isspace():
        index += 1
    return index


def declaration_start(masked: str, depth: list[int], offset: int, floor: int, level: int) -> int:
    """Inicio de la declaracion que contiene `offset`.

    Detalle que importa: la llave `{` que abre un metodo anterior tiene la **misma** profundidad
    que el miembro actual, pero no es su inicio. La frontera real es el `}` de cierre de ese
    miembro previo, una profundidad mas adentro.
    """
    index = offset - 1
    while index > floor:
        ch = masked[index]
        if depth[index] == level and ch == ";":
            return skip_whitespace(masked, index + 1, offset)
        if depth[index] == level + 1 and ch == "}":
            return skip_whitespace(masked, index + 1, offset)
        if depth[index] == level and ch == "}":
            break
        index -= 1
    return skip_whitespace(masked, floor, offset)


def strip_comment_args(text: str) -> str:
    return re.sub(r"//.*$", "", text, flags=re.MULTILINE)
