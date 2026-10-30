"""Ingesta web: descarga una vez, congela el texto y cita el snapshot.

Por qué un snapshot y no la página viva:

- una cita `url#párrafo` no es verificable si la página cambia (y cambian todas);
- la generación no puede depender de la red: el CI debe producir el mismo documento sin conexión;
- la frescura se vuelve comparable por hash: si el snapshot no coincide con la descarga nueva, la
  fuente está desactualizada.

Alcance declarado: HTML estático. **No** ejecuta JavaScript, así que una SPA servida vacía se detecta
como «sin texto útil» en lugar de documentarse como si no dijera nada.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urlparse

#: Topes defensivos: sin ellos, una URL puede colgar el proceso o llenar el disco.
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT_SECONDS = 20
MIN_TEXT_CHARS = 200
USER_AGENT = "docu/0.1 (+ingesta de documentación técnica; contacto: repo)"

SKIP_TAGS = frozenset(
    "script style noscript svg head iframe canvas template form nav footer aside".split()
)
BLOCK_TAGS = frozenset(
    "p div section article header h1 h2 h3 h4 h5 h6 li tr br table thead tbody ul ol pre blockquote "
    "figure figcaption main details summary".split()
)


class WebError(ValueError):
    """La fuente web no se pudo capturar con las garantías exigidas."""


@dataclass(frozen=True, slots=True)
class Snapshot:
    url: str
    text: str
    sha: str
    captured_at: str
    status_code: int = 200

    @property
    def lines(self) -> int:
        return len(self.text.splitlines())

    @property
    def usable(self) -> bool:
        return len(self.text.strip()) >= MIN_TEXT_CHARS

    @property
    def slug(self) -> str:
        parsed = urlparse(self.url)
        base = re.sub(r"[^a-z0-9]+", "-", (parsed.netloc + parsed.path).lower()).strip("-")
        return (base or "pagina")[:80]


class _TextExtractor(HTMLParser):
    """HTML → texto con saltos en los límites de bloque, sin dependencias."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag in BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        compact = [line for line in lines if line]
        deduped: list[str] = []
        for line in compact:
            if deduped and deduped[-1] == line:
                continue  # menús y cabeceras repetidas: ruido, no contenido
            deduped.append(line)
        return "\n".join(deduped)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text()


def is_allowed(url: str, allowlist: tuple[str, ...] | list[str]) -> bool:
    """Sólo http/https y sólo dominios declarados: la lista blanca es del proyecto, no del agente."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    for allowed in allowlist:
        candidate = allowed.lower().strip()
        if not candidate:
            continue
        if host == candidate or host.endswith("." + candidate):
            return True
    return False


def fetch(
    url: str,
    timeout: int = TIMEOUT_SECONDS,
    max_bytes: int = MAX_BYTES,
    opener=None,
    attempts: int = 2,
) -> tuple[str, int]:
    """Descarga el HTML. Devuelve (texto, código). `opener` permite inyectar uno en tests.

    Un fallo de red transitorio (TLS, timeout) es habitual: se reintenta una vez antes de declarar
    la fuente como no capturable.
    """
    open_url = opener or urllib.request.urlopen
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with open_url(request, timeout=timeout) as response:
                code = getattr(response, "status", 200)
                payload = response.read(max_bytes + 1)
            break
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt + 1 >= attempts:
                raise WebError(f"no se pudo descargar {url}: {error}") from error
            time.sleep(1.0)
    else:  # pragma: no cover - el bucle siempre rompe o lanza
        raise WebError(f"no se pudo descargar {url}: {last_error}")
    if len(payload) > max_bytes:
        raise WebError(f"{url} supera el tope de {max_bytes} bytes")
    charset = "utf-8"
    match = re.search(rb"charset=[\"']?([\w-]+)", payload[:2048], re.IGNORECASE)
    if match:
        charset = match.group(1).decode("ascii", "ignore")
    try:
        return payload.decode(charset, "replace"), int(code)
    except LookupError:
        return payload.decode("utf-8", "replace"), int(code)


def capture(url: str, allowlist: tuple[str, ...] | list[str], opener=None) -> Snapshot:
    """Captura una URL y devuelve su snapshot validado."""
    if not is_allowed(url, allowlist):
        raise WebError(
            f"{url} no está permitida: declara su dominio en el perfil "
            "(`sources.web.allowlist`) antes de capturarla"
        )
    html, code = fetch(url, opener=opener)
    text = html_to_text(html)
    snapshot = Snapshot(
        url=url,
        text=text,
        sha=__import__("hashlib").sha256(text.encode("utf-8")).hexdigest(),
        captured_at=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(timespec="seconds"),
        status_code=code,
    )
    if not snapshot.usable:
        raise WebError(
            f"{url} no tiene texto útil ({len(text)} caracteres): ¿es una SPA con JavaScript o una "
            "página de error? No se documenta una fuente vacía"
        )
    return snapshot


__all__ = [
    "MAX_BYTES",
    "MIN_TEXT_CHARS",
    "Snapshot",
    "WebError",
    "capture",
    "fetch",
    "html_to_text",
    "is_allowed",
]
