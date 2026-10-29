"""Frescura e idempotencia (Guia-v2.md §7).

El hash de entrada combina **seis** componentes, no tres: sin las versiones del embedder y del
chunker, un cambio de modelo deja el corpus silenciosamente inconsistente.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from docu.core.contracts import DocState, FreshnessRecord, utcnow, sha256_of

#: Orden canonico: cambiarlo invalida todos los hashes almacenados (a proposito y de golpe).
HASH_COMPONENTS: tuple[str, ...] = (
    "source_content",
    "deps_signature",
    "template",
    "embedder",
    "chunker",
    "profile",
)


@dataclass(frozen=True, slots=True)
class InputComponents:
    """Las seis entradas del hash. Cualquier componente vacio es un bug, no un caso borde."""

    source_content: str
    deps_signature: str
    template: str
    embedder: str
    chunker: str
    profile: str


def compute_input_hash(components: InputComponents) -> str:
    """Hash estable y explicito: nombre=valor, en orden canonico."""
    parts: list[str] = []
    for name in HASH_COMPONENTS:
        value = getattr(components, name)
        if not value:
            raise ValueError(f"componente de hash vacio: {name!r}")
        parts.append(f"{name}={value}")
    return sha256_of("|".join(parts))


def classify(
    *,
    stored_hash: str | None,
    current_hash: str,
    generated_at: datetime | None,
    ttl_days: int = 90,
    now: datetime | None = None,
) -> DocState:
    """Regla unica de estado.

    - sin hash previo            -> STALE (nunca generado)
    - hash distinto              -> STALE (fuente, vecinos, plantilla o versiones cambiaron)
    - sin fecha de generacion    -> STALE
    - TTL vencido                -> EXPIRED
    - resto                      -> FRESH
    """
    if stored_hash is None or generated_at is None:
        return DocState.STALE
    if stored_hash != current_hash:
        return DocState.STALE
    moment = now or utcnow()
    if moment - generated_at > timedelta(days=ttl_days):
        return DocState.EXPIRED
    return DocState.FRESH


def transition(
    *,
    node_id: str,
    record: FreshnessRecord | None,
    current_hash: str,
    now: datetime | None = None,
) -> FreshnessRecord:
    """Devuelve el registro de frescura actualizado sin mutar el anterior."""
    moment = now or utcnow()
    state = classify(
        stored_hash=record.input_hash if record else None,
        current_hash=current_hash,
        generated_at=record.generated_at if record else None,
        ttl_days=record.ttl_days if record else 90,
        now=moment,
    )
    return FreshnessRecord(
        node_id=node_id,
        input_hash=current_hash,
        state=state,
        generated_at=record.generated_at if record else moment,
        ttl_days=record.ttl_days if record else 90,
    )


def is_idempotent(*, previous_hash: str | None, current_hash: str) -> bool:
    """Ejecutar dos veces sobre el mismo commit debe producir diff vacio (Guia-v2.md §1)."""
    return previous_hash is not None and previous_hash == current_hash
