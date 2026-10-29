"""Lector de un subconjunto de YAML, sin dependencias externas.

Sirve para tres cosas del producto: el perfil (`docu.profile.yaml`), el modelo arquitectonico
prescriptivo y los contratos OpenAPI. Deliberadamente **no** implementa el lenguaje completo
(anclas, multi-documento, etiquetas): si un archivo los usa, se ignora esa parte en lugar de
interpretarla mal. Un lector honesto y limitado es mejor que una dependencia que nadie instala.
"""

from __future__ import annotations

__all__ = ["parse", "YamlError"]


class YamlError(ValueError):
    """El documento no pertenece al subconjunto soportado."""


def parse(text: str) -> dict[str, object]:
    """Devuelve un dict con el documento. Las claves de primer nivel son el contrato esperado."""
    lines = _prepare(text)
    if not lines:
        return {}
    value, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise YamlError(f"contenido no consumido a partir de la linea {lines[index][2]}")
    if not isinstance(value, dict):
        raise YamlError("la raiz del documento debe ser un mapa")
    return value


# --------------------------------------------------------------------------- preparacion


def _prepare(text: str) -> list[tuple[int, str, int]]:
    """(indentacion, contenido, numero de linea) ignorando vacias y comentarios."""
    prepared: list[tuple[int, str, int]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if raw.strip() in ("---", "..."):
            continue
        expanded = raw.replace("\t", "  ")
        content = _strip_comment(expanded).rstrip()
        if not content.strip():
            continue
        indent = len(content) - len(content.lstrip())
        prepared.append((indent, content.strip(), number))
    return prepared


def _strip_comment(line: str) -> str:
    """Quita comentarios de fin de linea respetando comillas."""
    quote: str | None = None
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            continue
        if char == "#" and (index == 0 or line[index - 1].isspace()):
            return line[:index]
    return line


# --------------------------------------------------------------------------- bloques


def _parse_block(
    lines: list[tuple[int, str, int]], start: int, indent: int
) -> tuple[object, int]:
    if lines[start][1].startswith("- "):
        return _parse_sequence(lines, start, indent)
    return _parse_mapping(lines, start, indent)


def _parse_mapping(
    lines: list[tuple[int, str, int]], start: int, indent: int
) -> tuple[dict[str, object], int]:
    result: dict[str, object] = {}
    index = start
    while index < len(lines):
        line_indent, content, number = lines[index]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise YamlError(f"indentacion inesperada en la linea {number}")
        if content.startswith("- "):
            break
        key, sep, rest = _split_key(content, number)
        if not sep:
            raise YamlError(f"se esperaba 'clave: valor' en la linea {number}")
        if rest[:1] in ("|", ">"):
            # Escalar de bloque (`run: |`, `command: >`): las líneas siguientes, más indentadas,
            # son el valor. Sin esto, un workflow real con `run: |` rompe toda la ingesta.
            marker = rest[0]
            index += 1
            block: list[str] = []
            while index < len(lines) and lines[index][0] > indent:
                block.append(lines[index][1])
                index += 1
            result[key] = ("\n" if marker == "|" else " ").join(block).strip()
            continue
        if rest:
            result[key] = _scalar(rest, number)
            index += 1
            continue
        index += 1
        if index < len(lines) and lines[index][0] > indent:
            child, index = _parse_block(lines, index, lines[index][0])
            result[key] = child
        elif index < len(lines) and lines[index][0] == indent and lines[index][1].startswith("- "):
            child, index = _parse_sequence(lines, index, indent)
            result[key] = child
        else:
            result[key] = None
    return result, index


def _parse_sequence(
    lines: list[tuple[int, str, int]], start: int, indent: int
) -> tuple[list[object], int]:
    items: list[object] = []
    index = start
    while index < len(lines):
        line_indent, content, number = lines[index]
        if line_indent < indent or not content.startswith("- "):
            break
        if line_indent > indent:
            raise YamlError(f"indentacion inesperada en la linea {number}")
        body = content[2:].strip()
        index += 1
        if not body:
            if index < len(lines) and lines[index][0] > indent:
                child, index = _parse_block(lines, index, lines[index][0])
                items.append(child)
            else:
                items.append(None)
            continue
        if _is_inline_mapping(body, number):
            mapping, index = _parse_inline_item(lines, index, indent, body, number)
            items.append(mapping)
            continue
        items.append(_scalar(body, number))
    return items, index


def _parse_inline_item(
    lines: list[tuple[int, str, int]],
    start: int,
    indent: int,
    first: str,
    number: int,
) -> tuple[dict[str, object], int]:
    """`- name: X` seguido de claves alineadas con `name`."""
    key, sep, rest = _split_key(first, number)
    if not sep:
        raise YamlError(f"elemento de secuencia invalido en la linea {number}")
    item: dict[str, object] = {key: _scalar(rest, number) if rest else None}
    index = start
    while index < len(lines):
        line_indent, content, child_number = lines[index]
        if line_indent <= indent:
            break
        if content.startswith("- "):
            break
        child_key, child_sep, child_rest = _split_key(content, child_number)
        if not child_sep:
            raise YamlError(f"se esperaba 'clave: valor' en la linea {child_number}")
        if child_rest[:1] in ("|", ">"):
            marker = child_rest[0]
            index += 1
            block_lines: list[str] = []
            while index < len(lines) and lines[index][0] > line_indent:
                block_lines.append(lines[index][1])
                index += 1
            item[child_key] = ("\n" if marker == "|" else " ").join(block_lines).strip()
            continue
        if child_rest:
            item[child_key] = _scalar(child_rest, child_number)
            index += 1
            continue
        index += 1
        if index < len(lines) and lines[index][0] > line_indent:
            child, index = _parse_block(lines, index, lines[index][0])
            item[child_key] = child
        elif index < len(lines) and lines[index][0] == line_indent and lines[index][1].startswith("- "):
            child, index = _parse_sequence(lines, index, line_indent)
            item[child_key] = child
        else:
            item[child_key] = None
    return item, index


# --------------------------------------------------------------------------- escalares


def _is_inline_mapping(body: str, number: int) -> bool:
    return bool(_split_key(body, number)[1])


def _split_key(content: str, number: int) -> tuple[str, str, str]:
    quote: str | None = None
    for index, char in enumerate(content):
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            continue
        if char == ":" and (index + 1 == len(content) or content[index + 1].isspace()):
            return content[:index].strip().strip("'\""), ":", content[index + 1 :].strip()
    return content, "", ""


def _scalar(value: str, number: int) -> object:
    text = value.strip()
    if not text:
        return None
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [_scalar(item, number) for item in _split_flow(inner)] if inner else []
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1].strip()
        result: dict[str, object] = {}
        for part in _split_flow(inner):
            key, _sep, rest = _split_key(part, number)
            result[key] = _scalar(rest, number) if rest else None
        return result
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    lowered = text.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if lowered in ("null", "~"):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _split_flow(text: str) -> list[str]:
    """Separa por comas respetando comillas y listas anidadas."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            current.append(char)
            continue
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if current:
        parts.append("".join(current).strip())
    return [part for part in parts if part]
