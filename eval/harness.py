"""Arnés de evaluación de F0 (Plan.md §5).

Mide el **retriever**, no la prosa: si el agente no trae la evidencia correcta, ninguna
métrica de generación posterior significa nada.

Referencia de F0: BM25 léxico puro sobre ventanas de líneas. Es deliberadamente ingenuo
—es la línea base que F1 (AST + metadatos) y F2 (híbrido + RRF) deben superar.

Métricas
--------
recall@k   fracción de archivos esperados que aparecen en el top-k (media por caso)
hit@k      1.0 si al menos un archivo esperado aparece en el top-k
MRR        1/rango del primer acierto
line_hit   acierto de ventana de líneas cuando el caso declara `lines`
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import statistics
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import log
from pathlib import Path
from typing import Iterable, Sequence

SCHEMA_VERSION = "1.0"

DEFAULT_MODEL_DIR = ".models/multilingual-minilm"

DEFAULT_INCLUDE = (
    "*.java",
    "*.xml",
    "*.yml",
    "*.yaml",
    "*.properties",
    "*.md",
    "*.imports",
    "*.tf",
    "*.sql",
    "Dockerfile",
)
DEFAULT_EXCLUDE = (
    # Artefactos de build
    "*/target/*",
    "target/*",
    "*/build/*",
    "build/*",
    "dist/*",
    "*/node_modules/*",
    "node_modules/*",
    "*.log",
    # Control de versiones
    "*/.git/*",
    ".git/*",
    # Higiene de corpus: el agente documenta el PRODUCTO, no el proceso del equipo.
    # En el piloto, los run-logs y contratos del propio flujo documental desplazaban
    # al codigo fuente en el ranking (fallo C-07 de la linea base).
    ".sdd/*",
    ".agents/*",
    "contracts/*",
    "mcp/*",
)

_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_WORD = re.compile(r"[\w.\-]+", re.UNICODE)

_STOP = frozenset(
    "de la el los las en y que con para por un una del al se como cual cuales donde qué cómo "
    "es son se su sus lo le que the a of and or in to is are for with on by".split()
)


# --------------------------------------------------------------------------- tokenización


def _fold(text: str) -> str:
    """Quita diacríticos: `configuración` y `configuracion` deben ser el mismo término.

    Un agente documentador en español se consulta indistintamente con y sin tildes; si el
    tokenizador las trata como palabras distintas, el recall cae por un motivo que no tiene
    nada que ver con la calidad del recuperador.
    """
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


def tokenize(text: str) -> list[str]:
    """Tokens con descomposición de CamelCase, separadores y plegado de acentos.

    Sin esto, BM25 puntúa identificadores Java como si fueran palabras opacas y el baseline
    queda artificialmente malo.
    """
    tokens: list[str] = []
    for raw in _WORD.findall(_fold(text)):
        for part in re.split(r"[_.\-]", raw):
            if not part:
                continue
            low = part.lower()
            if low not in _STOP:
                tokens.append(low)
            for match in _CAMEL.finditer(part):
                sub = match.group(0).lower()
                if len(sub) > 2 and sub not in _STOP:
                    tokens.append(sub)
    return tokens


# --------------------------------------------------------------------------- corpus


@dataclass(frozen=True, slots=True)
class Segment:
    """Unidad recuperable.

    En modo `windows` es una ventana de lineas; en modo `symbols` es un chunk del chunker
    sintactico de `docu`, con el nombre del simbolo como canal de coincidencia exacta.
    """

    path: str
    start: int
    end: int
    text: str
    tokens: tuple[str, ...] = ()
    exact_names: tuple[str, ...] = ()
    citation: str | None = None


def _matches(path: str, patterns: Sequence[str]) -> bool:
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(name, p) for p in patterns)


def discover_files(repo: Path, include: Sequence[str], exclude: Sequence[str]) -> list[str]:
    files: list[str] = []
    for candidate in sorted(repo.rglob("*")):
        if not candidate.is_file():
            continue
        rel = candidate.relative_to(repo).as_posix()
        if _matches(rel, exclude) or not _matches(rel, include):
            continue
        files.append(rel)
    return files


def _window_segments(repo: Path, rel: str, window: int, overlap: int) -> list[Segment]:
    try:
        text = (repo / rel).read_text(encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, OSError):
        return []
    lines = text.splitlines()
    if not lines:
        return []
    segments: list[Segment] = []
    step = max(1, window - overlap)
    for start in range(0, len(lines), step):
        block = lines[start : start + window]
        if not block:
            break
        body = "\n".join(block)
        if not body.strip():
            continue
        segments.append(
            Segment(
                path=rel,
                start=start + 1,
                end=start + len(block),
                text=body,
                tokens=tuple(tokenize(f"{rel} {body}")),
            )
        )
    return segments


def build_corpus(
    repo: Path,
    include: Sequence[str] = DEFAULT_INCLUDE,
    exclude: Sequence[str] = DEFAULT_EXCLUDE,
    window: int = 40,
    overlap: int = 8,
) -> list[Segment]:
    segments: list[Segment] = []
    for rel in discover_files(repo, include, exclude):
        segments.extend(_window_segments(repo, rel, window, overlap))
    return segments


def _exact_names(qualname: str | None) -> tuple[str, ...]:
    """Nombres por los que un simbolo debe coincidir de forma exacta (sin descomponer)."""
    if not qualname:
        return ()
    names = [qualname.lower()]
    names.extend(part.lower() for part in re.split(r"[.#]", qualname) if part)
    return tuple(dict.fromkeys(names))


def build_symbol_corpus(
    repo: Path,
    exclude: Sequence[str] = DEFAULT_EXCLUDE,
    window: int = 40,
    overlap: int = 8,
) -> list[Segment]:
    """Indice de F1: chunks sintacticos para Java y ventanas para el resto de artefactos.

    Mezclar ambos es deliberado: la documentacion de operacion vive en `application.yml`,
    `pom.xml` y `README.md`, y un indice que solo entienda Java perderia esos casos.
    """
    from docu.adapters.langs.java import JavaLangAdapter
    from docu.core.contracts import Artifact, SourceKind, sha256_of, utcnow
    from docu.index.chunker import SymbolChunker

    adapter = JavaLangAdapter()
    chunker = SymbolChunker()
    all_files = discover_files(repo, DEFAULT_INCLUDE, exclude)
    java_files = [rel for rel in all_files if rel.endswith(".java")]
    segments: list[Segment] = []

    for rel in java_files:
        try:
            source = (repo / rel).read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue
        artifact = Artifact(
            artifact_id=f"{repo.name}:{rel}",
            kind=SourceKind.GIT_REPOSITORY,
            uri=rel,
            content_hash=sha256_of(source.encode("utf-8")),
            captured_at=utcnow(),
            lang="java",
        )
        for chunk in chunker.chunk(artifact, adapter.symbols(rel, source), source):
            text = f"{chunk.content_prefix}\n{chunk.content}"
            segments.append(
                Segment(
                    path=chunk.file_path,
                    start=chunk.line_start,
                    end=chunk.line_end,
                    text=text,
                    tokens=tuple(tokenize(text)),
                    exact_names=_exact_names(chunk.enclosing_symbol),
                    citation=chunk.citation,
                )
            )

    java_set = set(java_files)
    for rel in all_files:
        if rel in java_set:
            continue
        segments.extend(_window_segments(repo, rel, window, overlap))
    return segments


# --------------------------------------------------------------------------- BM25


@dataclass
class BM25:
    """BM25 Okapi en stdlib. Canal lexico de ambos indices."""

    k1: float = 1.5
    b: float = 0.75
    segments: Sequence[Segment] = ()
    _df: dict[str, int] = field(default_factory=dict, init=False)
    _lengths: list[int] = field(default_factory=list, init=False)
    _avgdl: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        for segment in self.segments:
            self._lengths.append(len(segment.tokens))
            for term in set(segment.tokens):
                self._df[term] = self._df.get(term, 0) + 1
        self._avgdl = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0

    def _idf(self, term: str) -> float:
        n = len(self.segments)
        df = self._df.get(term, 0)
        return log(1 + (n - df + 0.5) / (df + 0.5))

    def scores(self, query: str) -> list[float]:
        terms = tokenize(query)
        results: list[float] = []
        for segment, length in zip(self.segments, self._lengths):
            freq: dict[str, int] = {}
            for token in segment.tokens:
                freq[token] = freq.get(token, 0) + 1
            score = 0.0
            for term in set(terms):
                tf = freq.get(term, 0)
                if tf == 0:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * (length / self._avgdl if self._avgdl else 1.0))
                score += self._idf(term) * (tf * (self.k1 + 1)) / denom
            results.append(score)
        return results

    def search(self, query: str, k: int = 10) -> list[tuple[Segment, float]]:
        scored = list(zip(self.segments, self.scores(query)))
        scored.sort(key=lambda item: item[1], reverse=True)
        return [(seg, score) for seg, score in scored[:k] if score > 0]


def _looks_like_identifier(query: str) -> bool:
    """¿La consulta es codigo tecleado o una pregunta humana?

    Criterio estricto, aprendido midiendo: una palabra capitalizada NO es un identificador.
    "Spring Boot" o "CORS" aparecen en preguntas humanas y enrutarlas al indice de simbolos
    empeoraba el MRR en espanol (0.596 -> 0.475). Se exige forma de codigo: punto entre
    palabras, guion bajo, o camelCase real.
    """
    for token in query.split():
        cleaned = token.strip('`"\'(),:;¿?¿!¡[]{}')
        if re.search(r"\w\.\w", cleaned):
            return True
        if "_" in cleaned:
            return True
        if re.search(r"\w-\w", cleaned):  # coordenadas Maven, kebab-case de CLI
            return True
        if re.search(r"[a-z][A-Z]", cleaned) or re.search(r"^[a-z]+[A-Z]", cleaned):
            return True
    return False


def _diversity(
    ordered: Sequence[tuple[tuple[str, int, int], float]],
    k: int,
    cap: int,
    by_key: dict[tuple[str, int, int], Segment],
) -> list[tuple[tuple[str, int, int], float]]:
    """Limita cuantos fragmentos aporta un mismo archivo (Guia-v2.md §3.4).

    Sin esto, un archivo con muchos chunks utiles ocupa casi todo el top-k y desplaza la
    evidencia de otros archivos: un documento generado asi cita ocho veces el mismo fichero.
    """
    out: list[tuple[tuple[str, int, int], float]] = []
    per_file: dict[str, int] = {}
    for key, score in ordered:
        path = by_key[key].path
        if per_file.get(path, 0) >= cap:
            continue
        per_file[path] = per_file.get(path, 0) + 1
        out.append((key, score))
        if len(out) >= k:
            break
    return out


@dataclass
class AutoIndex:
    """Indice de F2 con enrutado por tipo de consulta.

    Medido: los identificadores tecleados a mano rinden mejor con el indice de simbolos
    (1.000 vs 0.950) y las preguntas humanas rinden mejor con el hibrido (MRR 0.596 vs 0.518).
    Enrutar es mas honesto que inventar un promedio que empeora ambos casos.
    """

    segments: Sequence[Segment]
    embedder: object = None
    _symbols: SymbolIndex = field(init=False, repr=False)
    _hybrid: HybridIndex = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._symbols = SymbolIndex(segments=self.segments)
        self._hybrid = HybridIndex(segments=self.segments, embedder=self.embedder)

    def search(self, query: str, k: int = 10) -> list[tuple[Segment, float]]:
        if _looks_like_identifier(query):
            return self._symbols.search(query, k=k)
        return self._hybrid.search(query, k=k)


@dataclass
class HybridIndex:
    """Indice de F2: denso (multilingue) + lexico + coincidencia exacta de simbolo, fusionados.

    La fusion RRF es lo que evita que un canal aplaste a los demas: cada canal aporta su
    ranking, no su puntuacion, y las puntuaciones entre modelos no son comparables.
    """

    segments: Sequence[Segment]
    embedder: object = None
    k1: float = 1.5
    b: float = 0.75
    rrf_k: int = 60
    max_exact_per_file: int = 2
    max_per_file: int = 2
    _bm25: BM25 = field(init=False, repr=False)
    _by_name: dict[str, list[Segment]] = field(init=False, repr=False, default_factory=dict)
    _vectors: list[list[float]] = field(init=False, repr=False, default_factory=list)

    def __post_init__(self) -> None:
        self._bm25 = BM25(k1=self.k1, b=self.b, segments=self.segments)
        for segment in self.segments:
            for name in segment.exact_names:
                self._by_name.setdefault(name, []).append(segment)
        if self.embedder is not None:
            self._vectors = list(self.embedder.embed([segment.text for segment in self.segments]))

    # ------------------------------------------------------------------ canales

    def _dense_channel(self, query: str, limit: int) -> list[Segment]:
        if not self._vectors:
            return []
        from docu.adapters.embedders.onnx_local import cosine

        query_vector = self.embedder.embed([query])[0]  # type: ignore[union-attr]
        scored = [
            (segment, cosine(query_vector, vector))
            for segment, vector in zip(self.segments, self._vectors)
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return [segment for segment, _score in scored[:limit]]

    def _exact_channel(self, terms: set[str]) -> list[Segment]:
        hits: list[Segment] = []
        seen: set[tuple[str, int, int]] = set()
        per_file: dict[str, int] = {}
        for term in sorted(terms):
            for segment in self._by_name.get(term, ()):
                key = (segment.path, segment.start, segment.end)
                if key in seen or per_file.get(segment.path, 0) >= self.max_exact_per_file:
                    continue
                seen.add(key)
                per_file[segment.path] = per_file.get(segment.path, 0) + 1
                hits.append(segment)
        return hits

    def _channel_weights(self, query: str) -> tuple[float, float, float]:
        """Enrutado por tipo de consulta: si el usuario teclea identificadores, el canal denso pesa menos.

        Motivo medido: con consultas de identificadores el denso mete ruido y hace perder un caso
        (`pom.xml`, C-13) sin aportar nada; con preguntas humanas es imprescindible.
        """
        identifier_like = _looks_like_identifier(query)
        return (1.0, 0.5 if identifier_like else 1.0, 1.0)

    def search(self, query: str, k: int = 10) -> list[tuple[Segment, float]]:
        terms = set(tokenize(query))
        limit = max(k * 5, 50)
        channels = [
            [segment for segment, _score in self._bm25.search(query, k=limit)],
            self._dense_channel(query, limit),
            self._exact_channel(terms),
        ]
        weights = self._channel_weights(query)
        fused: dict[tuple[str, int, int], float] = {}
        by_key: dict[tuple[str, int, int], Segment] = {}
        for weight, channel in zip(weights, channels):
            for rank, segment in enumerate(channel, start=1):
                key = (segment.path, segment.start, segment.end)
                by_key[key] = segment
                fused[key] = fused.get(key, 0.0) + weight / (self.rrf_k + rank)
        ordered = sorted(fused.items(), key=lambda item: item[1], reverse=True)
        return [(by_key[key], score) for key, score in _diversity(ordered, k, self.max_per_file, by_key)]


@dataclass
class SymbolIndex:
    """Indice de F1: fusiona el canal lexico con un canal de coincidencia exacta de simbolo.

    Dos lecciones aprendidas midiendo:
    - Un refuerzo aditivo no funciona: los archivos con mas vocabulario comun ganan.
    - La prioridad absoluta tampoco: todos los chunks de un tipo coinciden y desplazan al
      recurso no-Java (`.imports`, `pom.xml`, `application.yml`) que responde la pregunta.
    Por eso se fusionan con RRF y el canal exacto se limita a dos chunks por archivo.
    """

    segments: Sequence[Segment]
    k1: float = 1.5
    b: float = 0.75
    rrf_k: int = 60
    max_exact_per_file: int = 2
    max_per_file: int = 2
    _bm25: BM25 = field(init=False, repr=False)
    _by_name: dict[str, list[Segment]] = field(init=False, repr=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._bm25 = BM25(k1=self.k1, b=self.b, segments=self.segments)
        for segment in self.segments:
            for name in segment.exact_names:
                self._by_name.setdefault(name, []).append(segment)

    def _exact_channel(self, terms: set[str]) -> list[Segment]:
        hits: list[Segment] = []
        seen: set[tuple[str, int, int]] = set()
        per_file: dict[str, int] = {}
        for term in sorted(terms):
            for segment in self._by_name.get(term, ()):
                key = (segment.path, segment.start, segment.end)
                if key in seen:
                    continue
                if per_file.get(segment.path, 0) >= self.max_exact_per_file:
                    continue
                seen.add(key)
                per_file[segment.path] = per_file.get(segment.path, 0) + 1
                hits.append(segment)
        return hits

    def search(self, query: str, k: int = 10) -> list[tuple[Segment, float]]:
        terms = set(tokenize(query))
        lexical = [segment for segment, _score in self._bm25.search(query, k=max(k * 5, 50))]
        exact = self._exact_channel(terms)

        fused: dict[tuple[str, int, int], float] = {}
        for rank, segment in enumerate(lexical, start=1):
            key = (segment.path, segment.start, segment.end)
            fused[key] = fused.get(key, 0.0) + 1.0 / (self.rrf_k + rank)
        for rank, segment in enumerate(exact, start=1):
            key = (segment.path, segment.start, segment.end)
            fused[key] = fused.get(key, 0.0) + 1.0 / (self.rrf_k + rank)

        by_key = {(s.path, s.start, s.end): s for s in list(lexical) + list(exact)}
        ordered = sorted(fused.items(), key=lambda item: item[1], reverse=True)
        return [(by_key[key], score) for key, score in _diversity(ordered, k, self.max_per_file, by_key)]


# --------------------------------------------------------------------------- evaluación


@dataclass(frozen=True, slots=True)
class Expected:
    path: str
    symbol: str | None = None
    lines: tuple[int, int] | None = None
    optional: bool = False


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    category: str
    question: str
    expected: tuple[Expected, ...]
    answer: str = ""
    notes: str = ""
    query: str = ""
    """Consulta de recuperación (identificadores, inglés). Si falta, se usa `question`."""

    @property
    def required_paths(self) -> tuple[str, ...]:
        return tuple(e.path for e in self.expected if not e.optional)

    def retrieval_query(self, field: str = "auto") -> str:
        if field == "question" or not self.query:
            return self.question
        return self.query


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    category: str
    recall: float
    hit: bool
    mrr: float
    line_hit: bool | None
    retrieved: tuple[str, ...]
    elapsed_ms: float


@dataclass
class Report:
    project: str
    k: int
    files: int
    segments: int
    results: list[CaseResult]
    query_field: str = "auto"
    index_mode: str = "windows"
    query_expansion: bool = False
    generated_at: str = ""
    schema_version: str = SCHEMA_VERSION

    def _agg(self, results: Sequence[CaseResult]) -> dict[str, float]:
        if not results:
            return {}
        line_results = [r.line_hit for r in results if r.line_hit is not None]
        return {
            "cases": len(results),
            "recall": statistics.fmean(r.recall for r in results),
            "hit_rate": sum(1 for r in results if r.hit) / len(results),
            "mrr": statistics.fmean(r.mrr for r in results),
            "line_accuracy": (sum(1 for x in line_results if x) / len(line_results)) if line_results else 0.0,
            "mean_ms": statistics.fmean(r.elapsed_ms for r in results),
        }

    @property
    def overall(self) -> dict[str, float]:
        return self._agg(self.results)

    def by_category(self) -> dict[str, dict[str, float]]:
        categories = sorted({r.category for r in self.results})
        return {cat: self._agg([r for r in self.results if r.category == cat]) for cat in categories}

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "k": self.k,
            "query_field": self.query_field,
            "index_mode": self.index_mode,
            "query_expansion": self.query_expansion,
            "files": self.files,
            "segments": self.segments,
            "generated_at": self.generated_at,
            "overall": self.overall,
            "by_category": self.by_category(),
            "cases": [
                {
                    "case_id": r.case_id,
                    "category": r.category,
                    "recall": round(r.recall, 4),
                    "hit": r.hit,
                    "mrr": round(r.mrr, 4),
                    "line_hit": r.line_hit,
                    "retrieved": list(r.retrieved),
                }
                for r in self.results
            ],
        }

    def to_markdown(self) -> str:
        o = self.overall
        lines = [
            f"# F0 — Línea base de recuperación · {self.project}",
            "",
            f"Generado: {self.generated_at} · k={self.k} · {self.files} archivos · {self.segments} segmentos",
            f"Índice: `{self.index_mode}` · consulta: `{self.query_field}` "
            "(identificadores/inglés si es `query`; pregunta en español si es `question`)"
            f" · expansión de consulta: `{'sí' if self.query_expansion else 'no'}`",
            "",
            "| Métrica | Valor |",
            "|---|---|",
            f"| recall@{self.k} | {o['recall']:.3f} |",
            f"| hit@{self.k} | {o['hit_rate']:.3f} |",
            f"| MRR | {o['mrr']:.3f} |",
            f"| acierto de líneas | {o['line_accuracy']:.3f} |",
            f"| latencia media | {o['mean_ms']:.1f} ms |",
            "",
            "## Por categoría",
            "",
            "| Categoría | Casos | recall | hit | MRR |",
            "|---|---|---|---|---|",
        ]
        for cat, agg in self.by_category().items():
            lines.append(
                f"| {cat} | {int(agg['cases'])} | {agg['recall']:.3f} | "
                f"{agg['hit_rate']:.3f} | {agg['mrr']:.3f} |"
            )
        lines += ["", "## Casos", "", "| Caso | Categoría | recall | hit | MRR | Top-1 recuperado |", "|---|---|---|---|---|---|"]
        for result in self.results:
            top = result.retrieved[0] if result.retrieved else "—"
            lines.append(
                f"| {result.case_id} | {result.category} | {result.recall:.2f} | "
                f"{'✅' if result.hit else '❌'} | {result.mrr:.2f} | `{top}` |"
            )
        return "\n".join(lines) + "\n"


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return not (a[1] < b[0] or b[1] < a[0])


def evaluate(
    cases: Sequence[Case],
    index: object,
    k: int = 10,
    query_field: str = "auto",
    expand: bool = False,
) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in cases:
        started = time.perf_counter()
        query = case.retrieval_query(query_field)
        if expand:
            from docu.retrieve.glossary import expand as expand_query

            query = expand_query(query)
        hits = index.search(query, k=k)  # type: ignore[attr-defined]
        elapsed_ms = (time.perf_counter() - started) * 1000

        required = set(case.required_paths)
        retrieved_paths = [seg.path for seg, _ in hits]

        found = {path for path in required if path in retrieved_paths}
        recall = len(found) / len(required) if required else 0.0

        mrr = 0.0
        for rank, path in enumerate(retrieved_paths, start=1):
            if path in required:
                mrr = 1.0 / rank
                break

        # Acierto de líneas: solo cuando el caso declara el rango exacto de la evidencia.
        line_hit: bool | None = None
        ranged = [e for e in case.expected if e.lines is not None and not e.optional]
        if ranged:
            line_hit = any(
                seg.path == exp.path and _overlaps((seg.start, seg.end), exp.lines)  # type: ignore[arg-type]
                for exp in ranged
                for seg, _ in hits
            )

        results.append(
            CaseResult(
                case_id=case.id,
                category=case.category,
                recall=recall,
                hit=bool(found),
                mrr=mrr,
                line_hit=line_hit,
                retrieved=tuple(retrieved_paths),
                elapsed_ms=elapsed_ms,
            )
        )
    return results


# --------------------------------------------------------------------------- carga


def load_golden(path: Path) -> tuple[str, str, list[Case]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases: list[Case] = []
    for raw in payload["cases"]:
        expected = tuple(
            Expected(
                path=item["path"],
                symbol=item.get("symbol"),
                lines=tuple(item["lines"]) if item.get("lines") else None,  # type: ignore[arg-type]
                optional=bool(item.get("optional", False)),
            )
            for item in raw["expected"]
        )
        cases.append(
            Case(
                id=raw["id"],
                category=raw.get("category", "general"),
                question=raw["question"],
                expected=expected,
                answer=raw.get("answer", ""),
                notes=raw.get("notes", ""),
                query=raw.get("query", ""),
            )
        )
    return payload.get("project", path.stem), payload.get("repo", ""), cases


# --------------------------------------------------------------------------- CLI


def run(
    golden_path: Path,
    repo: Path | None,
    k: int,
    out_dir: Path,
    quiet: bool = False,
    query_field: str = "auto",
    label: str = "",
    index_mode: str = "windows",
    model_dir: str = DEFAULT_MODEL_DIR,
    expand: bool = False,
) -> Report:
    project, repo_from_golden, cases = load_golden(golden_path)
    root = repo or Path(repo_from_golden)
    if not root.exists():
        raise SystemExit(f"error: repositorio no encontrado: {root}")

    if index_mode == "hybrid":
        from docu.adapters.embedders.onnx_local import OnnxEmbedder

        embedder = OnnxEmbedder(model_dir=model_dir)
        if not embedder.available:
            raise SystemExit(f"error: modelo ONNX no encontrado en {model_dir!r}")
        segments = build_symbol_corpus(root)
        index: AutoIndex | HybridIndex | SymbolIndex | BM25 = HybridIndex(
            segments=segments, embedder=embedder
        )
    elif index_mode == "auto":
        from docu.adapters.embedders.onnx_local import OnnxEmbedder

        embedder = OnnxEmbedder(model_dir=model_dir)
        segments = build_symbol_corpus(root)
        index = AutoIndex(segments=segments, embedder=embedder if embedder.available else None)
    elif index_mode == "symbols":
        segments = build_symbol_corpus(root)
        index = SymbolIndex(segments=segments)
    else:
        segments = build_corpus(root)
        index = BM25(segments=segments)
    results = evaluate(cases, index, k=k, query_field=query_field, expand=expand)
    report = Report(
        project=project,
        k=k,
        files=len(discover_files(root, DEFAULT_INCLUDE, DEFAULT_EXCLUDE)),
        segments=len(segments),
        results=results,
        query_field=query_field,
        index_mode=index_mode,
        query_expansion=expand,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    stem = f"f0-{project}{label}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / f"{stem}.md").write_text(report.to_markdown(), encoding="utf-8")

    if not quiet:
        o = report.overall
        print(
            f"{project} [{query_field}]: recall@{k}={o['recall']:.3f} hit={o['hit_rate']:.3f} "
            f"MRR={o['mrr']:.3f} lineas={o['line_accuracy']:.3f} | {report.segments} segmentos"
        )
        missed = [r.case_id for r in results if not r.hit]
        if missed:
            print(f"fallos: {', '.join(missed)}")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Arnés de evaluación F0 de docu")
    parser.add_argument("--golden", required=True, help="ruta del golden set (.json)")
    parser.add_argument("--repo", default=None, help="sobrescribe el repo del golden set")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--out", default="eval/reports", help="directorio de informes")
    parser.add_argument(
        "--query-field",
        choices=["auto", "query", "question"],
        default="auto",
        help="qué texto se usa como consulta: identificadores (query) o la pregunta tal cual",
    )
    parser.add_argument(
        "--index",
        choices=["windows", "symbols", "hybrid", "auto"],
        default="windows",
        help="windows: ventanas (F0) · symbols: chunks + match exacto (F1) · hybrid: +denso · auto: enruta por consulta",
    )
    parser.add_argument(
        "--model-dir",
        default=DEFAULT_MODEL_DIR,
        help=f"directorio del modelo ONNX (default: {DEFAULT_MODEL_DIR})",
    )
    parser.add_argument("--label", default="", help="sufijo del nombre del informe")
    parser.add_argument(
        "--expand",
        action="store_true",
        help="expande la consulta con el glosario de dominio (eval/glossary.py)",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = run(
        Path(args.golden),
        Path(args.repo) if args.repo else None,
        args.k,
        Path(args.out),
        args.quiet,
        query_field=args.query_field,
        label=args.label,
        index_mode=args.index,
        model_dir=args.model_dir,
        expand=args.expand,
    )
    return 0 if report.overall.get("hit_rate", 0.0) > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
