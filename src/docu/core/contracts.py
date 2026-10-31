"""Contratos de datos del motor.

Decision deliberada: **solo stdlib**. Todo contrato es serializable a JSON y lleva
`schema_version`, para que un indice viejo nunca se lea con un esquema nuevo por accidente.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "1.0"


# --------------------------------------------------------------------------- utilidades


def utcnow() -> datetime:
    """Reloj unico del sistema: siempre UTC con zona explicita."""
    return datetime.now(timezone.utc)


def sha256_of(data: str | bytes) -> str:
    payload = data.encode("utf-8") if isinstance(data, str) else data
    return "sha256:" + hashlib.sha256(payload).hexdigest()


# --------------------------------------------------------------------------- enumeraciones


class SourceKind(str, Enum):
    GIT_REPOSITORY = "git_repository"
    PDF = "pdf"
    WEB = "web"
    OPENAPI = "openapi"
    SQL = "sql"
    IAC = "iac"
    ADR = "adr"


class SymbolKind(str, Enum):
    MODULE = "module"
    CLASS = "class"
    INTERFACE = "interface"
    ENUM = "enum"
    FUNCTION = "function"
    METHOD = "method"
    CONSTRUCTOR = "constructor"
    FIELD = "field"
    HTTP_ROUTE = "http_route"
    SQL_TABLE = "sql_table"
    CONFIG_KEY = "config_key"
    UNKNOWN = "unknown"


class DocState(str, Enum):
    """Frescura de una pagina (Guia-v2.md §7)."""

    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"
    #: El manifest declara la página pero el archivo no está en disco. No es «fresco» ni «viejo»:
    #: es inexistente, y confundirlo con frescura es un éxito silencioso.
    MISSING = "missing"


class Mode(str, Enum):
    """Grado de autonomia (Guia-v2.md §7)."""

    PROPOSE = "propose"
    APPLY = "apply"
    PUBLISH = "publish"


class GateOutcome(str, Enum):
    """Resultado de evaluar las compuertas de calidad."""

    PUBLISH = "publish"
    REVIEW = "review"
    ABORT = "abort"


# --------------------------------------------------------------------------- artefactos fuente


@dataclass(frozen=True, slots=True)
class Artifact:
    """Unidad de entrada tal como la entrega un `SourceAdapter`.

    `snapshot_path` es obligatorio para fuentes volatiles (web, PDF remoto): sin snapshot
    no hay reproducibilidad y, por tanto, la fuente no es citable.
    """

    artifact_id: str
    kind: SourceKind
    uri: str
    content_hash: str
    captured_at: datetime
    lang: str | None = None
    snapshot_path: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.artifact_id:
            raise ValueError("artifact_id vacio")
        if self.kind in (SourceKind.WEB, SourceKind.PDF) and not self.snapshot_path:
            raise ValueError(
                f"fuente volatil {self.uri!r} requiere snapshot_path: sin snapshot no es citable"
            )


@dataclass(frozen=True, slots=True)
class Symbol:
    """Simbolo extraido del codigo por un `LangAdapter`."""

    name: str
    qualname: str
    kind: SymbolKind
    path: str
    line_start: int
    line_end: int
    signature: str | None = None
    children: Sequence["Symbol"] = ()
    annotations: Sequence[str] = ()
    schema_version: str = SCHEMA_VERSION

    @property
    def is_container(self) -> bool:
        return self.kind in (SymbolKind.CLASS, SymbolKind.INTERFACE, SymbolKind.ENUM, SymbolKind.MODULE)


# --------------------------------------------------------------------------- chunk indexado


@dataclass(frozen=True, slots=True)
class Chunk:
    """Bloque indexado. El prefijo es obligatorio: es la senal de contexto que usa el modelo."""

    chunk_id: str
    artifact_id: str
    source_type: SourceKind
    content: str
    content_prefix: str
    content_hash: str
    file_path: str
    lang: str | None
    enclosing_symbol: str | None
    symbol_kind: SymbolKind
    line_start: int
    line_end: int
    ingested_at: datetime
    repo: str | None = None
    commit: str | None = None
    dependencies: Sequence[str] = ()
    embed_model: str | None = None
    chunker: str = "ast-v2"
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.content_prefix:
            raise ValueError("content_prefix vacio: rompe la trazabilidad contextual")
        if self.line_start < 1 or self.line_end < self.line_start:
            raise ValueError(f"rango de lineas invalido: {self.line_start}-{self.line_end}")

    @property
    def citation(self) -> str:
        """Referencia humana y estable para insertar en el documento."""
        return f"{self.file_path}#L{self.line_start}-L{self.line_end}"

    def to_record(self) -> dict[str, Any]:
        """Forma plana para el vector store."""
        return {
            "chunk_id": self.chunk_id,
            "artifact_id": self.artifact_id,
            "source_type": self.source_type.value,
            "file_path": self.file_path,
            "lang": self.lang,
            "enclosing_symbol": self.enclosing_symbol,
            "symbol_kind": self.symbol_kind.value,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "repo": self.repo,
            "commit": self.commit,
            "dependencies": list(self.dependencies),
            "content_hash": self.content_hash,
            "embed_model": self.embed_model,
            "chunker": self.chunker,
            "ingested_at": self.ingested_at.isoformat(),
            "citation": self.citation,
            "schema_version": self.schema_version,
        }


# --------------------------------------------------------------------------- generacion


@dataclass(frozen=True, slots=True)
class Claim:
    """Una afirmacion del documento y las evidencias que la sostienen.

    Invariante del producto: un `Claim` sin `evidence` no puede publicarse (Guia-v2.md §3.5).
    """

    text: str
    evidence: Sequence[str] = ()

    @property
    def verified(self) -> bool:
        return len(self.evidence) > 0


@dataclass(slots=True)
class ContentNode:
    """Nodo del grafo de contenido: **fuente unica de verdad** de los cuatro niveles.

    Un hecho (p. ej. el puerto 8080) existe aqui una sola vez y se renderiza con distinta
    profundidad; nunca se reescribe por nivel.
    """

    node_id: str
    kind: str
    title: str
    claims: list[Claim] = field(default_factory=list)
    levels: tuple[str, ...] = ("l1",)
    state: DocState = DocState.FRESH
    confidence: float = 0.0
    rendered: dict[str, str] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    @property
    def unsupported(self) -> list[Claim]:
        return [c for c in self.claims if not c.verified]

    def is_publishable(self) -> bool:
        return not self.unsupported and self.state is DocState.FRESH


# --------------------------------------------------------------------------- evaluacion


@dataclass(frozen=True, slots=True)
class Metrics:
    """Las seis metricas del producto (Guia-v2.md §5). Escala 1-10 salvo las indicadas."""

    accuracy: float
    completeness: float
    attribution: float
    conciseness: float
    freshness: float = 10.0
    cost_usd: float = 0.0
    unsupported_claims: int = 0
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Salida de `policy.evaluate`: la unica forma en que el agente decide publicar."""

    outcome: GateOutcome
    reasons: tuple[str, ...] = ()

    @property
    def may_write(self) -> bool:
        """PROPOSE nunca escribe; REVIEW escribe en rama y abre PR; PUBLISH publica."""
        return self.outcome is not GateOutcome.ABORT

    def describe(self) -> str:
        head = self.outcome.value.upper()
        return f"{head}: " + "; ".join(self.reasons) if self.reasons else head


# --------------------------------------------------------------------------- trazabilidad de corridas


@dataclass(slots=True)
class RunRecord:
    """Una fila del ledger local (`.docu/ledger.jsonl`). Base del aprendizaje."""

    run_id: str
    project: str
    commit: str | None
    mode: Mode
    started_at: datetime
    finished_at: datetime | None = None
    versions: dict[str, str] = field(default_factory=dict)
    metrics: Metrics | None = None
    gate: GateDecision | None = None
    pages_written: int = 0
    pages_skipped: int = 0
    cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    @property
    def duration_s(self) -> float | None:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    def to_jsonl(self) -> str:
        payload = {
            "run_id": self.run_id,
            "project": self.project,
            "commit": self.commit,
            "mode": self.mode.value,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_s": self.duration_s,
            "versions": self.versions,
            "metrics": asdict(self.metrics) if self.metrics else None,
            "gate": {"outcome": self.gate.outcome.value, "reasons": list(self.gate.reasons)}
            if self.gate
            else None,
            "pages_written": self.pages_written,
            "pages_skipped": self.pages_skipped,
            "cost_usd": self.cost_usd,
            "errors": self.errors,
            "schema_version": self.schema_version,
        }
        return json.dumps(payload, ensure_ascii=False)


# --------------------------------------------------------------------------- frescura


@dataclass(frozen=True, slots=True)
class FreshnessRecord:
    """Estado de frescura de una pagina (Guia-v2.md §7)."""

    node_id: str
    input_hash: str
    state: DocState
    generated_at: datetime
    ttl_days: int = 90
    schema_version: str = SCHEMA_VERSION

    def is_expired(self, now: datetime | None = None) -> bool:
        moment = now or utcnow()
        return moment - self.generated_at > timedelta(days=self.ttl_days)
