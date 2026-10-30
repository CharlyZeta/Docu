"""Extracción de texto de PDF sin dependencias externas.

Alcance declarado, porque una promesa grande aquí se paga cara:

- **Sí**: PDF con streams sin comprimir o `FlateDecode` (lo que produce casi todo el software que
  genera PDFs), texto en operadores `Tj`/`TJ`/`'`/`"`, escapes octales y hexadecimales, y `ToUnicode`
  CMap para fuentes con codificación propia.
- **No**: PDF escaneado (imagen), PDF cifrado, fuentes con codificación exótica sin `ToUnicode`, ni
  reconstrucción de tablas o columnas.

Cuando la extracción no alcanza, el resultado lo **dice** (`warning` + `chars`) en lugar de devolver
texto basura: un documento que cita mal es peor que uno que admite no haber podido.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from typing import Iterable

OBJECT_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj\b(.*?)\bendobj", re.DOTALL)
STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\n?endstream", re.DOTALL)
PAGE_RE = re.compile(rb"/Type\s*/Page\b")
CONTENTS_RE = re.compile(rb"/Contents\s*(\[[^\]]*\]|\d+\s+\d+\s+R)")
REF_RE = re.compile(rb"(\d+)\s+\d+\s+R")
BFCHAR_RE = re.compile(rb"beginbfchar(.*?)endbfchar", re.DOTALL)
BFRANGE_RE = re.compile(rb"beginbfrange(.*?)endbfrange", re.DOTALL)
HEXPAIR_RE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
HEXRANGE_RE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")

#: Mínimo de caracteres por página para considerar que el PDF tiene texto.
MIN_CHARS_PER_PAGE = 20


class PdfError(ValueError):
    """El archivo no es un PDF legible por este extractor."""


FONT_OBJECT_RE = re.compile(rb"/Type\s*/Font\b")
FONT_RESOURCES_RE = re.compile(rb"/Font\s*(<<.*?>>|\d+\s+\d+\s+R)", re.DOTALL)
FONT_ENTRY_RE = re.compile(rb"/([A-Za-z0-9_.+-]+)\s+(\d+)\s+\d+\s+R")
TF_RE = re.compile(rb"/([A-Za-z0-9_.+-]+)\s+[\d.]+\s+Tf")
TYPE0_RE = re.compile(rb"/Subtype\s*/Type0\b")


def _object_of(value: bytes) -> bytes:
    """Cuerpo del objeto si `value` es una referencia `N G R`; si no, el valor tal cual."""
    match = REF_RE.fullmatch(value.strip())
    return b"" if match is None else match.group(0)


def _font_map(objects: dict[int, bytes]) -> dict[str, tuple[dict[int, str], bool]]:
    """Mapa `/F1 → (cmap, dos_bytes)` a partir de los recursos de cada página.

    Es lo que separa «extraer texto» de «extraer basura»: un PDF real usa **una fuente subset por
    rol** (cuerpo, negrita, símbolos), cada una con su propio `ToUnicode`. Aplicar un único mapa
    global produce texto cifrado que parece texto.
    """
    fonts: dict[str, tuple[dict[int, str], bool]] = {}
    for body in objects.values():
        if PAGE_RE.search(body) is None and b"/Font" not in body:
            continue
        for resource in FONT_RESOURCES_RE.finditer(body):
            block = resource.group(1)
            if block.startswith(b"<<") is False:
                referenced = objects.get(int(REF_RE.search(block).group(1)), b"") if REF_RE.search(block) else b""
                block = referenced
            for name, number in FONT_ENTRY_RE.findall(block):
                font_body = objects.get(int(number), b"")
                cmap: dict[int, str] = {}
                to_unicode = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", font_body)
                if to_unicode:
                    stream = _stream_of(objects.get(int(to_unicode.group(1)), b""))
                    if stream:
                        cmap = _parse_cmap(stream)
                two_byte = bool(TYPE0_RE.search(font_body))
                key = name.decode("latin-1")
                if cmap or key not in fonts:
                    fonts[key] = (cmap, two_byte)
    return fonts


def _decode_with(raw: bytes, cmap: dict[int, str] | None, two_byte: bool) -> str:
    if not cmap:
        return raw.decode("latin-1", "replace")
    if two_byte:
        text = "".join(
            cmap.get((raw[index] << 8) | raw[index + 1], "")
            for index in range(0, len(raw) - 1, 2)
        )
        if text:
            return text
    return "".join(cmap.get(byte, chr(byte)) for byte in raw)


def _looks_like_garbage(text: str) -> bool:
    """Detecta texto que el extractor produjo pero que no es legible.

    Un PDF con fuentes subset mal mapeadas devuelve algo así como `P r e M H J e B D p e K`. Se
    prefiere marcar la extracción como dudosa antes que citar basura: el documento generado sería
    peor que no tenerlo.
    """
    compact = "".join(text.split())
    if len(compact) < 40:
        return False
    letters = sum(1 for char in compact if char.isalpha())
    spaces = text.count(" ")
    single_char_tokens = sum(1 for token in text.split() if len(token) == 1)
    tokens = max(1, len(text.split()))
    if letters / len(compact) < 0.55:
        return True
    if single_char_tokens / tokens > 0.55:
        return True
    if spaces and len(compact) / spaces < 2.0:
        return True
    return False


@dataclass(frozen=True, slots=True)
class PdfPage:
    number: int
    text: str


@dataclass(slots=True)
class PdfText:
    pages: tuple[PdfPage, ...] = ()
    total_pages: int = 0
    chars: int = 0
    method: str = "desconocido"
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def usable(self) -> bool:
        """¿Hay texto suficiente para citar algo, o es un PDF escaneado?"""
        if self.total_pages <= 0:
            return False
        return self.chars >= MIN_CHARS_PER_PAGE * self.total_pages

    @property
    def status(self) -> str:
        if self.usable:
            return "texto extraído"
        if self.total_pages and self.chars:
            return "texto insuficiente (posible PDF escaneado o con codificación no soportada)"
        return "sin texto extraíble (PDF escaneado, cifrado o corrupto)"


def is_pdf(path: str, data: bytes | None = None) -> bool:
    if path.lower().endswith(".pdf"):
        return True
    return bool(data and data.startswith(b"%PDF"))


# --------------------------------------------------------------------------- streams


def _decode(stream: bytes) -> bytes:
    """Descomprime un stream si está en FlateDecode; si no, lo devuelve tal cual."""
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS, zlib.MAX_WBITS | 32):
        try:
            return zlib.decompress(stream, wbits)
        except zlib.error:
            continue
    return stream


def _objects(data: bytes) -> dict[int, bytes]:
    """Objetos del documento, indexados por número."""
    found: dict[int, bytes] = {}
    for match in OBJECT_RE.finditer(data):
        found[int(match.group(1))] = match.group(3)
    return found


def _stream_of(body: bytes) -> bytes | None:
    match = STREAM_RE.search(body)
    if match is None:
        return None
    return _decode(match.group(1))


# --------------------------------------------------------------------------- fuentes


def _parse_cmap(text: bytes) -> dict[int, str]:
    """`ToUnicode` CMap: códigos de byte → carácter, para fuentes con codificación propia."""
    mapping: dict[int, str] = {}
    for block in BFCHAR_RE.finditer(text):
        for source, target in HEXPAIR_RE.findall(block.group(1)):
            try:
                mapping[int(source, 16)] = bytes.fromhex(target.decode()).decode("utf-16-be", "ignore")
            except (ValueError, UnicodeDecodeError):
                continue
    for block in BFRANGE_RE.finditer(text):
        for low, high, target in HEXRANGE_RE.findall(block.group(1)):
            try:
                start, end = int(low, 16), int(high, 16)
                base = bytes.fromhex(target.decode()).decode("utf-16-be", "ignore")
            except (ValueError, UnicodeDecodeError):
                continue
            for offset, code in enumerate(range(start, min(end, start + 255) + 1)):
                if base:
                    mapping[code] = chr(ord(base[0]) + offset) if len(base) == 1 else base
    return mapping


def _cmap_for(objects: dict[int, bytes]) -> dict[int, str]:
    """CMap `ToUnicode`: por referencia explícita o, si el PDF no la declara bien, por contenido.

    Muchos generadores escriben el CMap sin que el diccionario de fuente lo referencie de forma
    estándar; buscar el bloque `beginbfchar` es más tolerante sin inventar nada: se sigue leyendo el
    mapa que el propio documento trae.
    """
    for body in objects.values():
        if b"/ToUnicode" not in body:
            continue
        stream = _stream_of(body)
        if stream is None:
            continue
        mapping = _parse_cmap(stream)
        if mapping:
            return mapping
    for body in objects.values():
        stream = _stream_of(body)
        if stream is None or (b"beginbfchar" not in stream and b"beginbfrange" not in stream):
            continue
        mapping = _parse_cmap(stream)
        if mapping:
            return mapping
    return {}


# --------------------------------------------------------------------------- contenido


def _decode_bytes(raw: bytes, cmap: dict[int, str]) -> str:
    if cmap:
        if len(cmap) and max(cmap) > 255:
            text = "".join(
                cmap.get((raw[index] << 8) | raw[index + 1], "")
                for index in range(0, len(raw) - 1, 2)
            )
            if text:
                return text
        return "".join(cmap.get(byte, chr(byte)) for byte in raw)
    return raw.decode("latin-1", "replace")


def _literal(data: bytes, index: int) -> tuple[bytes, int]:
    """Cadena literal `( … )` con escapes, incluidas las anidadas."""
    depth = 1
    out = bytearray()
    index += 1
    while index < len(data) and depth:
        char = data[index]
        if char == 0x5C:  # barra invertida
            index += 1
            if index >= len(data):
                break
            escape = data[index]
            mapping = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
            if escape in mapping:
                out.append(mapping[escape])
            elif 0x30 <= escape <= 0x37:
                digits = bytes([escape])
                while index + 1 < len(data) and 0x30 <= data[index + 1] <= 0x37 and len(digits) < 3:
                    index += 1
                    digits += bytes([data[index]])
                out.append(int(digits, 8) & 0xFF)
            elif escape in (0x0A, 0x0D):
                pass  # continuación de línea: no aporta
            else:
                out.append(escape)
        elif char == 0x28:
            depth += 1
            out.append(char)
        elif char == 0x29:
            depth -= 1
            if depth:
                out.append(char)
        else:
            out.append(char)
        index += 1
    return bytes(out), index


def _hexstring(data: bytes, index: int) -> tuple[bytes, int]:
    end = data.find(b">", index)
    if end == -1:
        return b"", len(data)
    digits = re.sub(rb"[^0-9A-Fa-f]", b"", data[index + 1 : end])
    if len(digits) % 2:
        digits += b"0"
    try:
        return bytes.fromhex(digits.decode()), end + 1
    except ValueError:
        return b"", end + 1


def _content_text(
    data: bytes,
    cmap: dict[int, str],
    fonts: dict[str, tuple[dict[int, str], bool]] | None = None,
) -> str:
    """Texto de un content stream: `Tj`, `TJ`, `'` y `"`, con saltos por `Td`/`TD`/`T*`/`Tm`.

    El mapa de decodificación se elige por fuente (`Tf`): cada subset trae el suyo.
    """
    fonts = fonts or {}
    active_cmap, active_two_byte = cmap, False
    pieces: list[str] = []
    pending: bytes | None = None
    numbers: list[float] = []
    last_y: float | None = None
    index = 0
    size = len(data)

    def flush(separator: str = "") -> None:
        nonlocal pending
        if pending is None:
            return
        pieces.append(_decode_with(pending, active_cmap, active_two_byte))
        pieces.append(separator)
        pending = None

    while index < size:
        if data[index] == 0x2F:  # `/Nombre 12 Tf`
            font_match = re.match(rb"/([A-Za-z0-9_.+-]+)\s+[\d.]+\s+Tf", data[index:])
            if font_match:
                name = font_match.group(1).decode("latin-1")
                if name in fonts:
                    active_cmap, active_two_byte = fonts[name]
                index += font_match.end()
                numbers.clear()
                continue
            index += 1
            continue
        char = data[index]
        if char == 0x28:  # (
            text, index = _literal(data, index)
            pending = text if pending is None else pending + text
            continue
        if char == 0x3C and index + 1 < size and data[index + 1] == 0x3C:
            # Diccionario `<< … >>`: se salta entero. Si no hay cierre, se termina el stream:
            # `(find + 2) or size` daba 1 con find == -1 y colgaba el proceso.
            closing = data.find(b">>", index)
            index = size if closing == -1 else closing + 2
            continue
        if char == 0x3C:  # <hex>
            text, index = _hexstring(data, index)
            pending = text if pending is None else pending + text
            continue
        if char in b"0123456789+-.":
            number_match = re.match(rb"[-+]?[\d.]+", data[index:])
            if number_match:
                try:
                    numbers.append(float(number_match.group(0)))
                except ValueError:
                    pass
                index += number_match.end()
                continue
        if char == 0x5B:  # [ … ]  (arreglo de TJ: los números negativos grandes son espacios)
            array: list[bytes] = []
            pieces_tj: list[bytes] = []
            index += 1
            depth = 1
            while index < size and depth:
                if data[index] == 0x5B:
                    depth += 1
                elif data[index] == 0x5D:
                    depth -= 1
                    if depth == 0:
                        break
                elif data[index] == 0x28:
                    item, index = _literal(data, index)
                    pieces_tj.append(item)
                    continue
                elif data[index] == 0x3C and index + 1 < size and data[index + 1] != 0x3C:
                    item, index = _hexstring(data, index)
                    pieces_tj.append(item)
                    continue
                elif data[index] in b"0123456789+-.":
                    kerning = re.match(rb"[-+]?[\d.]+", data[index:])
                    if kerning:
                        try:
                            if float(kerning.group(0)) < -100:
                                pieces_tj.append(b" ")
                        except ValueError:
                            pass
                        index += kerning.end()
                        continue
                index += 1
            index += 1
            if pieces_tj:
                joined = b"".join(pieces_tj)
                pending = joined if pending is None else pending + joined
            continue
        # Operadores de posición: sólo separan si de verdad cambian de línea o de columna.
        if data.startswith(b"Td", index) or data.startswith(b"TD", index):
            if len(numbers) >= 2:
                tx, ty = numbers[-2], numbers[-1]
                if abs(ty) > 0.5:
                    flush("\n")
                elif abs(tx) > 0.5:
                    flush(" ")
            numbers.clear()
            index += 2
            continue
        if data.startswith(b"Tm", index):
            if len(numbers) >= 6:
                y = numbers[-1]
                if last_y is None or abs(y - last_y) > 0.5:
                    flush("\n")
                else:
                    flush(" ")
                last_y = y
            numbers.clear()
            index += 2
            continue
        if data.startswith(b"T*", index):
            flush("\n")
            numbers.clear()
            index += 2
            continue
        if data.startswith(b"Tj", index) or data.startswith(b"TJ", index):
            flush("")
            numbers.clear()
            index += 2
            continue
        if char == 0x27:  # '  (siguiente línea + mostrar)
            flush("\n")
            numbers.clear()
            index += 1
            continue
        if char == 0x22:  # "  (espaciado + siguiente línea + mostrar)
            flush("\n")
            numbers.clear()
            index += 1
            continue
        if char in b" \t\r\n":
            numbers.clear()
        index += 1

    flush("")
    text = "".join(pieces)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    return text.strip()


# --------------------------------------------------------------------------- documento


def _page_streams(objects: dict[int, bytes]) -> list[bytes]:
    """Streams de cada página, en el orden del documento."""
    streams: list[bytes] = []
    for number in sorted(objects):
        body = objects[number]
        if not PAGE_RE.search(body):
            continue
        contents = CONTENTS_RE.search(body)
        if contents is None:
            streams.append(b"")
            continue
        page_data = bytearray()
        for ref in REF_RE.findall(contents.group(1)):
            stream = _stream_of(objects.get(int(ref), b""))
            if stream:
                page_data.extend(stream + b"\n")
        streams.append(bytes(page_data))
    return streams


def extract(data: bytes) -> PdfText:
    """Texto por página, con método usado y avisos. Nunca lanza por contenido inválido."""
    warnings: list[str] = []
    if not data.startswith(b"%PDF"):
        return PdfText(warnings=("el archivo no empieza con %PDF",))
    if b"/Encrypt" in data:
        return PdfText(warnings=("PDF cifrado: no se descifra",))

    objects = _objects(data)
    streams = _page_streams(objects)
    cmap = _cmap_for(objects)
    fonts = _font_map(objects)
    method = "sin comprimir"
    if b"/FlateDecode" in data:
        method = "FlateDecode"

    if not streams:
        # Sin objetos de página: se intenta con todos los streams (PDFs minimalistas de prueba).
        streams = [stream for stream in (_stream_of(body) for body in objects.values()) if stream]
        if streams:
            warnings.append("sin objetos de página: se extrajo de todos los streams")
        method = f"{method} (sin estructura de páginas)"

    pages: list[PdfPage] = []
    for index, stream in enumerate(streams, start=1):
        text = _content_text(stream, cmap, fonts)
        pages.append(PdfPage(index, text))
    chars = sum(len(page.text) for page in pages)
    if cmap:
        method = f"{method} + ToUnicode"
    if not chars:
        warnings.append("no se extrajo texto: PDF escaneado o con codificación no soportada")

    return PdfText(
        pages=tuple(pages),
        total_pages=len(pages),
        chars=chars,
        method=method,
        warnings=tuple(warnings),
    )


def pages_text(result: PdfText) -> str:
    """Texto plano con separadores de página, listo para escribir un sidecar."""
    blocks: Iterable[str] = (
        f"--- página {page.number} ---\n{page.text}" for page in result.pages if page.text
    )
    return "\n\n".join(blocks)


__all__ = [
    "MIN_CHARS_PER_PAGE",
    "PdfError",
    "PdfPage",
    "PdfText",
    "extract",
    "is_pdf",
    "pages_text",
]
