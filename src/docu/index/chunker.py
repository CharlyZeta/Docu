"""Segmentacion sintactica (Guia-v2.md §3.2).

Regla del producto: **un simbolo por chunk**. Un tipo aporta su *cascara* (anotaciones,
declaracion y campos) y cada metodo su propio bloque; el cuerpo de los metodos no se repite
dentro del chunk del tipo. Asi se evita el doble conteo y cada chunk sigue siendo una unidad
semantica completa.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from docu.core.contracts import Artifact, Chunk, Symbol, SymbolKind, sha256_of, utcnow

DEFAULT_CHUNKER = "ast-v2"
CHARS_PER_TOKEN = 4

CONTAINER_KINDS = (SymbolKind.CLASS, SymbolKind.INTERFACE, SymbolKind.ENUM, SymbolKind.MODULE)


def estimate_tokens(text: str) -> int:
    """Estimacion deliberadamente simple y estable: ~4 caracteres por token."""
    return max(1, len(text) // CHARS_PER_TOKEN)


def _flatten(symbols: Sequence[Symbol]) -> tuple[Symbol, ...]:
    """Tipos y sus miembros en un solo recorrido, sin duplicar contenedores."""
    out: list[Symbol] = []
    seen: set[str] = set()

    def visit(symbol: Symbol) -> None:
        if symbol.qualname in seen:
            return
        seen.add(symbol.qualname)
        out.append(symbol)
        for child in symbol.children:
            visit(child)

    for symbol in symbols:
        visit(symbol)
    return tuple(out)


@dataclass(frozen=True, slots=True)
class SymbolChunker:
    """Chunker por simbolos: implementa el puerto `Chunker`."""

    name: str = DEFAULT_CHUNKER
    max_tokens: int = 1024
    overlap_tokens: int = 128

    def chunk(
        self,
        artifact: Artifact,
        symbols: Sequence[Symbol],
        source: str,
        dependencies: Mapping[str, Sequence[str]] | None = None,
    ) -> tuple[Chunk, ...]:
        lines = source.splitlines()
        if not lines:
            return ()

        routes = {symbol.qualname: symbol.name for symbol in symbols if symbol.kind is SymbolKind.HTTP_ROUTE}
        chunks: list[Chunk] = []
        for symbol in _flatten(symbols):
            if symbol.kind is SymbolKind.HTTP_ROUTE:
                continue  # su informacion viaja en el prefijo del metodo
            start, end = self._span(symbol, symbols, lines)
            body = "\n".join(lines[start - 1 : end])
            if not body.strip():
                continue
            prefix = self._prefix(artifact, symbol, start, end, routes.get(symbol.qualname))
            chunks.extend(
                self._split(
                    artifact=artifact,
                    symbol=symbol,
                    prefix=prefix,
                    body=body,
                    start=start,
                    end=end,
                    dependencies=(dependencies or {}).get(symbol.path, ()),
                )
            )
        return tuple(chunks)

    # ------------------------------------------------------------------ geometria

    def _span(self, symbol: Symbol, symbols: Sequence[Symbol], lines: Sequence[str]) -> tuple[int, int]:
        """Rango de lineas del simbolo; para contenedores termina antes del primer hijo."""
        if symbol.kind not in CONTAINER_KINDS:
            return symbol.line_start, min(symbol.line_end, len(lines))
        child_starts = [
            child.line_start
            for child in symbol.children
            if child.line_start > symbol.line_start
        ]
        end = (min(child_starts) - 1) if child_starts else symbol.line_end
        return symbol.line_start, max(symbol.line_start, min(end, len(lines)))

    def _prefix(
        self,
        artifact: Artifact,
        symbol: Symbol,
        start: int,
        end: int,
        route: str | None,
    ) -> str:
        """Metadatos inyectados: sin esto el fragmento pierde su procedencia."""
        parts = [f"File: {symbol.path}"]
        if symbol.kind in CONTAINER_KINDS:
            parts.append(f"Type: {symbol.kind.value} {symbol.name}")
        else:
            container = symbol.qualname.rsplit(".", 1)[0]
            parts.append(f"Type: {container}")
            parts.append(f"Symbol: {symbol.qualname}")
        if route:
            parts.append(f"Route: {route}")
        if symbol.annotations:
            parts.append("Annotations: " + " ".join(symbol.annotations))
        parts.append(f"lines {start}-{end}")
        if artifact.uri and artifact.uri != symbol.path:
            parts.append(f"source {artifact.uri}")
        return "[" + " | ".join(parts) + "]"

    # ------------------------------------------------------------------ segmentacion

    def _split(
        self,
        *,
        artifact: Artifact,
        symbol: Symbol,
        prefix: str,
        body: str,
        start: int,
        end: int,
        dependencies: Sequence[str],
    ) -> list[Chunk]:
        """Un chunk si cabe; si no, ventanas con solapamiento alineadas a lineas."""
        total = estimate_tokens(body)
        base_id = f"{artifact.artifact_id}#{symbol.qualname}"
        if total <= self.max_tokens:
            return [
                self._make(
                    chunk_id=base_id,
                    artifact=artifact,
                    symbol=symbol,
                    prefix=prefix,
                    content=body,
                    start=start,
                    end=end,
                    dependencies=dependencies,
                )
            ]

        window = self.max_tokens * CHARS_PER_TOKEN
        step = max(1, (self.max_tokens - self.overlap_tokens) * CHARS_PER_TOKEN)
        chunks: list[Chunk] = []
        offset = 0
        part = 1
        while offset < len(body):
            piece = body[offset : offset + window]
            piece_start = start + body[:offset].count("\n")
            piece_end = min(end, piece_start + piece.count("\n"))
            chunks.append(
                self._make(
                    chunk_id=f"{base_id}:part{part}",
                    artifact=artifact,
                    symbol=symbol,
                    prefix=f"{prefix} part {part}",
                    content=piece,
                    start=piece_start,
                    end=piece_end,
                    dependencies=dependencies,
                )
            )
            if offset + window >= len(body):
                break
            offset += step
            part += 1
        return chunks

    def _make(
        self,
        *,
        chunk_id: str,
        artifact: Artifact,
        symbol: Symbol,
        prefix: str,
        content: str,
        start: int,
        end: int,
        dependencies: Sequence[str],
    ) -> Chunk:
        return Chunk(
            chunk_id=chunk_id,
            artifact_id=artifact.artifact_id,
            source_type=artifact.kind,
            content=content,
            content_prefix=prefix,
            content_hash=sha256_of(f"{self.name}|{prefix}|{content}"),
            file_path=symbol.path,
            lang=artifact.lang,
            enclosing_symbol=symbol.qualname,
            symbol_kind=symbol.kind,
            line_start=start,
            line_end=max(start, end),
            ingested_at=utcnow(),
            dependencies=tuple(dependencies),
            chunker=self.name,
        )
