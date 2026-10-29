"""Recuperación híbrida sobre el **código**: el motor que la medición de F2 validó.

Tres canales, fusión RRF y enrutado por forma de consulta:

- **léxico**: BM25 sobre el chunk con su prefijo de metadatos;
- **estructural**: coincidencia exacta de nombre de símbolo (lo que BM25 no puede inferir);
- **denso**: embeddings multilingües, si el modelo está disponible.

Medido en `eval/README.md`: 1.000 de recall@10 con identificadores y 0.850 con preguntas en español.
Este módulo es la versión de producto: el arnés conserva su copia como banco de pruebas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from docu.adapters.langs.registry import adapter_for
from docu.core.contracts import Artifact, SourceKind, sha256_of, utcnow
from docu.generate.pipeline import EXCLUDED_PARTS, _discover, _is_test_path, _path_matches, _read
from docu.index.chunker import SymbolChunker
from docu.retrieve.glossary import expand
from docu.retrieve.search import looks_like_identifier, tokenize

RRF_K = 60
DENSE_CHUNK_LIMIT = 4000
MAX_PER_FILE = 2


@dataclass(frozen=True, slots=True)
class CodeChunk:
    """Fragmento de código recuperable, con su cita y su símbolo."""

    path: str
    start: int
    end: int
    text: str
    symbol: str | None
    kind: str
    tokens: tuple[str, ...] = ()
    exact_names: tuple[str, ...] = ()

    @property
    def citation(self) -> str:
        return f"{self.path}#L{self.start}-L{self.end}"

    def to_dict(self, score: float) -> dict[str, object]:
        return {
            "citation": self.citation,
            "path": self.path,
            "start": self.start,
            "end": self.end,
            "symbol": self.symbol,
            "kind": self.kind,
            "score": round(score, 4),
            "excerpt": self.text[:1200],
        }


def _exact_names(qualname: str | None) -> tuple[str, ...]:
    if not qualname:
        return ()
    names = [qualname.lower()]
    names.extend(part.lower() for part in qualname.replace(".", " ").split())
    return tuple(dict.fromkeys(names))


def build_chunks(
    root: Path | str,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    include_tests: bool = False,
) -> list[CodeChunk]:
    """Chunks sintácticos de todos los archivos de código soportados en el proyecto."""
    root_path = Path(root)
    chunker = SymbolChunker()
    chunks: list[CodeChunk] = []
    for rel, path in _discover(
        root_path, include_tests=include_tests, include=include, exclude=exclude
    ).items():
        adapter = adapter_for(rel)
        if adapter is None:
            continue
        source = _read(path)
        artifact = Artifact(
            artifact_id=f"{root_path.name}:{rel}",
            kind=SourceKind.GIT_REPOSITORY,
            uri=rel,
            content_hash=sha256_of(source.encode("utf-8")),
            captured_at=utcnow(),
            lang=str(adapter.language),  # type: ignore[attr-defined]
        )
        for chunk in chunker.chunk(artifact, adapter.symbols(rel, source), source):  # type: ignore[attr-defined]
            text = f"{chunk.content_prefix}\n{chunk.content}"
            chunks.append(
                CodeChunk(
                    path=chunk.file_path,
                    start=chunk.line_start,
                    end=chunk.line_end,
                    text=text,
                    symbol=chunk.enclosing_symbol,
                    kind=chunk.symbol_kind.value,
                    tokens=tuple(tokenize(text)),
                    exact_names=_exact_names(chunk.enclosing_symbol),
                )
            )
    return chunks


@dataclass
class CodeIndex:
    """Índice de código con los tres canales. El denso es opcional y se declara."""

    chunks: list[CodeChunk] = field(default_factory=list)
    embedder: object | None = None
    glossary: Mapping[str, Sequence[str]] | None = None
    k1: float = 1.5
    b: float = 0.75
    _df: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _lengths: list[int] = field(default_factory=list, init=False, repr=False)
    _avgdl: float = field(default=0.0, init=False, repr=False)
    _by_name: dict[str, list[CodeChunk]] = field(default_factory=dict, init=False, repr=False)
    _vectors: list[Sequence[float]] = field(default_factory=list, init=False, repr=False)
    _dense_ready: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self._lengths = [len(chunk.tokens) for chunk in self.chunks]
        for chunk in self.chunks:
            for term in set(chunk.tokens):
                self._df[term] = self._df.get(term, 0) + 1
            for name in chunk.exact_names:
                self._by_name.setdefault(name, []).append(chunk)
        self._avgdl = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0

    # ------------------------------------------------------------------ capacidades

    @property
    def dense_available(self) -> bool:
        return self.embedder is not None

    def capabilities(self) -> dict[str, object]:
        return {
            "chunks": len(self.chunks),
            "channels": ["lexical", "symbol"] + (["dense"] if self.dense_available else []),
            "dense": self.dense_available,
            "files": len({chunk.path for chunk in self.chunks}),
        }

    # ------------------------------------------------------------------ canales

    def _idf(self, term: str) -> float:
        total = len(self.chunks)
        df = self._df.get(term, 0)
        return math.log(1 + (total - df + 0.5) / (df + 0.5))

    def _lexical(self, terms: set[str], limit: int) -> list[CodeChunk]:
        scored: list[tuple[CodeChunk, float]] = []
        for chunk, length in zip(self.chunks, self._lengths):
            counts: dict[str, int] = {}
            for token in chunk.tokens:
                if token in terms:
                    counts[token] = counts.get(token, 0) + 1
            if not counts:
                continue
            score = 0.0
            for term, frequency in counts.items():
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * (length / self._avgdl if self._avgdl else 1.0)
                )
                score += self._idf(term) * (frequency * (self.k1 + 1)) / denominator
            scored.append((chunk, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return [chunk for chunk, _score in scored[:limit]]

    def _structural(self, terms: set[str]) -> list[CodeChunk]:
        hits: list[CodeChunk] = []
        seen: set[str] = set()
        per_file: dict[str, int] = {}
        for term in sorted(terms):
            for chunk in self._by_name.get(term, ()):
                key = chunk.citation
                if key in seen or per_file.get(chunk.path, 0) >= MAX_PER_FILE:
                    continue
                seen.add(key)
                per_file[chunk.path] = per_file.get(chunk.path, 0) + 1
                hits.append(chunk)
        return hits

    def _dense(self, query: str, limit: int) -> list[CodeChunk]:
        if self.embedder is None:
            return []
        from docu.adapters.embedders.onnx_local import cosine

        if not self._dense_ready:
            sample = self.chunks[:DENSE_CHUNK_LIMIT]
            vectors = list(self.embedder.embed([chunk.text for chunk in sample]))  # type: ignore[attr-defined]
            self._vectors = vectors
            self._dense_ready = True
        if not self._vectors:
            return []
        query_vector = self.embedder.embed([query])[0]  # type: ignore[attr-defined]
        scored = [
            (chunk, cosine(query_vector, vector))
            for chunk, vector in zip(self.chunks[:DENSE_CHUNK_LIMIT], self._vectors)
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return [chunk for chunk, _score in scored[:limit]]

    # ------------------------------------------------------------------ busqueda

    def search(self, query: str, limit: int = 10, expand_query: bool = True) -> list[tuple[CodeChunk, float]]:
        """Fusiona los canales con RRF y aplica diversidad por archivo."""
        if not self.chunks:
            return []
        text = expand(query, self.glossary) if expand_query else query
        terms = set(tokenize(text))
        if not terms:
            return []
        window = max(limit * 5, 50)
        identifier_like = looks_like_identifier(query)
        channels: list[tuple[float, list[CodeChunk]]] = [
            (1.0, self._lexical(terms, window)),
            (1.0 if identifier_like else 0.6, self._structural(terms)),
        ]
        dense = self._dense(text, window)
        if dense:
            channels.append((0.5 if identifier_like else 1.0, dense))

        fused: dict[str, float] = {}
        by_key: dict[str, CodeChunk] = {}
        for weight, channel in channels:
            for rank, chunk in enumerate(channel, start=1):
                by_key[chunk.citation] = chunk
                fused[chunk.citation] = fused.get(chunk.citation, 0.0) + weight / (RRF_K + rank)

        ordered = sorted(fused.items(), key=lambda item: item[1], reverse=True)
        results: list[tuple[CodeChunk, float]] = []
        per_file: dict[str, int] = {}
        for citation, score in ordered:
            chunk = by_key[citation]
            if per_file.get(chunk.path, 0) >= MAX_PER_FILE:
                continue
            per_file[chunk.path] = per_file.get(chunk.path, 0) + 1
            results.append((chunk, score))
            if len(results) >= limit:
                break
        return results


def build_index(
    root: Path | str,
    *,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    include_tests: bool = False,
    model_dir: Path | str | None = None,
    dense: bool = True,
    glossary: Mapping[str, Sequence[str]] | None = None,
) -> CodeIndex:
    """Construye el índice, con canal denso solo si el modelo está disponible."""
    chunks = build_chunks(root, include=include, exclude=exclude, include_tests=include_tests)
    embedder = None
    if dense:
        from docu.adapters.embedders.onnx_local import OnnxEmbedder, resolve_model_dir

        directory = Path(model_dir) if model_dir else resolve_model_dir(root)
        if directory is not None:
            candidate = OnnxEmbedder(model_dir=directory)
            if candidate.available:
                embedder = candidate
    return CodeIndex(chunks=chunks, embedder=embedder, glossary=glossary)


__all__ = [
    "CodeChunk",
    "CodeIndex",
    "DENSE_CHUNK_LIMIT",
    "EXCLUDED_PARTS",
    "build_chunks",
    "build_index",
    "_is_test_path",
    "_path_matches",
]
