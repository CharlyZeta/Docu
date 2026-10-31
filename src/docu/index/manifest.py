"""Manifest de frescura: la memoria que hace incremental al agente.

Un documento no se compara por fecha, se compara por **hash de seis entradas**. Si el contenido,
las dependencias, la plantilla, el embedder, el chunker o el perfil cambian, la pagina esta `stale`
aunque el archivo no se haya tocado.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Mapping

from docu.core.contracts import DocState, sha256_of, utcnow
from docu.index.freshness import InputComponents, classify, compute_input_hash

MANIFEST_PATH = ".docu/manifest.json"
MANIFEST_VERSION = "1.0"

#: Versiones que invalidan el indice si cambian. Se declaran aqui, no se infieren.
DEFAULT_VERSIONS: dict[str, str] = {
    "docu": "0.1.0",
    "renderer": "1",
    "chunker": "ast-v2",
    "tokenizer": "es-fold-v1",
    "embedder": "none",
}


@dataclass(frozen=True, slots=True)
class DocEntry:
    """Estado registrado de una pagina generada."""

    level: str
    path: str
    input_hash: str
    generated_at: str
    content_hash: str
    ttl_days: int = 90
    sources: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "level": self.level,
            "path": self.path,
            "input_hash": self.input_hash,
            "generated_at": self.generated_at,
            "content_hash": self.content_hash,
            "ttl_days": self.ttl_days,
            "sources": dict(self.sources),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "DocEntry":
        return cls(
            level=str(payload["level"]),
            path=str(payload["path"]),
            input_hash=str(payload["input_hash"]),
            generated_at=str(payload["generated_at"]),
            content_hash=str(payload["content_hash"]),
            ttl_days=int(payload.get("ttl_days", 90)),  # type: ignore[arg-type]
            sources=dict(payload.get("sources") or {}),  # type: ignore[arg-type]
        )

    def generated_at_dt(self) -> datetime:
        return datetime.fromisoformat(self.generated_at)


@dataclass(slots=True)
class Manifest:
    """Conjunto de paginas conocidas de un proyecto."""

    project: str
    docs: list[DocEntry] = field(default_factory=list)
    versions: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_VERSIONS))
    schema_version: str = MANIFEST_VERSION

    # ------------------------------------------------------------------ consulta

    def entry(self, level: str) -> DocEntry | None:
        return next((doc for doc in self.docs if doc.level == level), None)

    def upsert(self, entry: DocEntry) -> None:
        self.docs = [doc for doc in self.docs if doc.level != entry.level] + [entry]

    # ------------------------------------------------------------------ persistencia

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "versions": dict(self.versions),
            "docs": [doc.to_dict() for doc in self.docs],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "Manifest":
        return cls(
            project=str(payload.get("project", "")),
            docs=[DocEntry.from_dict(item) for item in payload.get("docs", [])],  # type: ignore[union-attr]
            versions=dict(payload.get("versions") or DEFAULT_VERSIONS),  # type: ignore[arg-type]
            schema_version=str(payload.get("schema_version", MANIFEST_VERSION)),
        )

    def save(self, path: Path | str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: Path | str) -> "Manifest | None":
        target = Path(path)
        if not target.exists():
            return None
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return cls.from_dict(payload)


# --------------------------------------------------------------------------- calculo


def input_hash_for(
    *,
    level: str,
    sources: Mapping[str, str],
    fact_signature: str,
    versions: Mapping[str, str],
    profile_digest: str,
) -> str:
    """Hash de seis entradas para una pagina concreta."""
    content = sha256_of("|".join(f"{path}:{sha}" for path, sha in sorted(sources.items())))
    return compute_input_hash(
        InputComponents(
            source_content=content,
            deps_signature=fact_signature or "none",
            template=f"{level}@{versions.get('renderer', '1')}",
            embedder=versions.get("embedder", "none"),
            chunker=versions.get("chunker", "ast-v2"),
            profile=profile_digest or "default",
        )
    )


def fact_signature(facts: object) -> str:
    """Huella de la estructura de dependencias: si cambian los módulos o las deps, cambia."""
    pairs = sorted(
        f"{item.kind}:{item.subject}"
        for item in facts  # type: ignore[union-attr]
        if getattr(item, "kind", "") in ("module", "dependency", "parent")
    )
    return sha256_of("|".join(pairs)) if pairs else "none"


def state_of(
    *,
    entry: DocEntry | None,
    current_hash: str,
    now: datetime | None = None,
    ttl_days: int = 90,
    file_exists: bool = True,
) -> DocState:
    """Estado de la página. Sin entrada en el manifest equivale a `stale`: nunca se ha generado.

    Un hash intacto con el archivo borrado **no** es frescura: es un registro que miente. Se devuelve
    `MISSING`, distinto de `STALE`, para que el mensaje pueda decir qué hacer: generar de nuevo, no
    incrementar.
    """
    if entry is None:
        return DocState.STALE
    if not file_exists:
        return DocState.MISSING
    return classify(
        stored_hash=entry.input_hash,
        current_hash=current_hash,
        generated_at=entry.generated_at_dt(),
        ttl_days=ttl_days,
        now=now or utcnow(),
    )


def document_exists(entry: DocEntry | None, root: Path) -> bool:
    """¿Sigue existiendo el archivo que el manifest dice haber generado?"""
    if entry is None or not entry.path:
        return False
    path = Path(entry.path)
    if not path.is_absolute():
        path = root / path
    return path.exists()


def profile_digest(root: Path) -> str:
    """Huella del perfil del proyecto, si existe: cambiarlo invalida todo lo generado.

    Se normalizan los finales de línea para que el mismo perfil dé la misma huella en Windows y
    en Linux; si no, el CI acusaría páginas obsoletas por un `\\r\\n`.
    """
    for name in ("docu.profile.yaml", "docu.profile.yml", "docu.profile.json"):
        candidate = root / name
        if candidate.exists():
            text = candidate.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
            return sha256_of(text)
    return "default"
