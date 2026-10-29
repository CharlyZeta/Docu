"""Puertos del motor (Plan.md §2, Guia-v2.md §4).

Ocho contratos y nada mas. El nucleo depende **solo** de estos `Protocol`; cualquier
implementacion concreta vive en `docu.adapters.*` y se descubre por entry points.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Protocol, Sequence, runtime_checkable

from docu.core.contracts import Artifact, Chunk, ContentNode, Metrics, Symbol


# --------------------------------------------------------------------------- ingesta


@runtime_checkable
class SourceAdapter(Protocol):
    """Trae artefactos de una fuente (git, pdf, web, openapi, sql, iac)."""

    name: str
    kind: type

    def discover(self, root: str, include: Sequence[str], exclude: Sequence[str]) -> Iterable[Artifact]:
        ...

    def read(self, artifact: Artifact) -> str | bytes:
        ...


@runtime_checkable
class LangAdapter(Protocol):
    """Extrae estructura de codigo. Uno por lenguaje; ningun `if lang ==` en el nucleo.

    Debe pasar `tests/conformance_langs/` sin tocar `core/`.
    """

    language: str
    file_globs: Sequence[str]

    def symbols(self, path: str, source: str) -> Sequence[Symbol]:
        ...

    def imports(self, path: str, source: str) -> Sequence[str]:
        ...

    def calls(self, path: str, source: str) -> Sequence[tuple[str, str]]:
        """Aristas (llamador, llamado) solo cuando son **estaticamente verificables**.

        El despacho dinamico no se inventa: se omite o se marca con confianza baja.
        """
        ...


@runtime_checkable
class Chunker(Protocol):
    """Segmentacion sintactica: un simbolo por chunk cuando cabe; nunca corte por tamano ciego."""

    name: str

    def chunk(self, artifact: Artifact, symbols: Sequence[Symbol], source: str) -> Sequence[Chunk]:
        ...


# --------------------------------------------------------------------------- recuperacion


@runtime_checkable
class Embedder(Protocol):
    """Embeddings intercambiables. `embedder_id` incluye modelo y dimension: entra en el hash."""

    embedder_id: str
    dim: int

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        ...


@runtime_checkable
class VectorStore(Protocol):
    """Almacen vectorial detras de un puerto: Chroma hoy, pgvector o Qdrant mañana."""

    store_id: str

    def upsert(self, namespace: str, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> int:
        ...

    def query(
        self, namespace: str, vector: Sequence[float], top_k: int, filters: Mapping[str, Any] | None = None
    ) -> Sequence[tuple[Chunk, float]]:
        ...

    def delete_by_filter(self, namespace: str, filters: Mapping[str, Any]) -> int:
        ...


@runtime_checkable
class Reranker(Protocol):
    """Cross-encoder: reordena el par consulta-fragmento. Segunda etapa tras la fusion RRF."""

    reranker_id: str

    def rank(self, query: str, chunks: Sequence[Chunk], top_n: int) -> Sequence[tuple[Chunk, float]]:
        ...


# --------------------------------------------------------------------------- generacion y salida


@runtime_checkable
class RenderAdapter(Protocol):
    """Convierte un nodo del grafo de contenido en texto de un nivel/notacion concreto."""

    name: str
    target: str

    def render(self, node: ContentNode, context: Mapping[str, Any]) -> str:
        ...


@runtime_checkable
class Judge(Protocol):
    """Evaluador separado del generador, con version pinneada (Guia-v2.md §5)."""

    judge_id: str
    temperature: float

    def score(self, document: str, evidence: Sequence[Chunk], rubric: Mapping[str, Any]) -> Metrics:
        ...


@runtime_checkable
class Publisher(Protocol):
    """Destino final. `revert` es obligatorio: la autonomia sin reversibilidad es un riesgo."""

    publisher_id: str

    def propose(self, path: str, content: str, message: str) -> str:
        ...

    def apply(self, proposal_id: str) -> str:
        ...

    def revert(self, applied_id: str) -> None:
        ...


__all__ = [
    "SourceAdapter",
    "LangAdapter",
    "Chunker",
    "Embedder",
    "VectorStore",
    "Reranker",
    "RenderAdapter",
    "Judge",
    "Publisher",
]
