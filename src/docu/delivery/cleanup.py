"""`docu clean`: volver a cero sin borrar lo que no generó `docu`.

Reglas de seguridad, porque un comando de borrado mal hecho es peor que no tenerlo:

1. **Simulación por defecto**: sin `--force` sólo se lista lo que se borraría.
2. **Sólo artefactos conocidos**: `*.md` de la raíz del directorio de salida, y los subdirectorios
   `diagrams/`, `web/`, `pdf/`, `site/`. Nunca un borrado recursivo del directorio entero: si alguien
   apuntó `--out` a una carpeta con documentación escrita a mano, no se toca.
3. **Nunca fuera de la raíz del proyecto** (salvo que el usuario lo pida con `--out` explícito, y ahí
   se avisa).
4. **El ledger no se borra por defecto**: es historial de aprendizaje, no un artefacto de salida.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from docu.core.contracts import sha256_of

DOC_SUFFIXES = (".md",)
#: Sólo se borran documentos con el nombre que genera docu (l1-manual-tecnico.md, …).
#: Si alguien generó dentro de docs/, su README.md o su guia.md no se tocan.
GENERATED_DOC_RE = re.compile(r"^l\d+-.+\.md$")
ARTIFACT_DIRS = ("diagrams", "web", "pdf", "site")
STATE_FILES = ("manifest.json", "web.json", "prose.json")
LEDGER_FILE = "ledger.jsonl"
STATE_DIR = ".docu"


@dataclass(slots=True)
class CleanPlan:
    """Lo que se borraría (o se borró), separado por tipo para poder revisarlo."""

    documents: list[Path] = field(default_factory=list)
    artifacts: list[Path] = field(default_factory=list)
    state: list[Path] = field(default_factory=list)
    ledger: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.documents or self.artifacts or self.state or self.ledger)

    @property
    def total(self) -> int:
        return len(self.documents) + len(self.artifacts) + len(self.state) + len(self.ledger)

    def to_dict(self) -> dict[str, object]:
        return {
            "documents": [str(path) for path in self.documents],
            "artifacts": [str(path) for path in self.artifacts],
            "state": [str(path) for path in self.state],
            "ledger": [str(path) for path in self.ledger],
            "warnings": list(self.warnings),
            "total": self.total,
        }


def _iter_files(directory: Path) -> Iterable[Path]:
    if not directory.is_dir():
        return []
    return (path for path in sorted(directory.rglob("*")) if path.is_file())


def plan(
    root: Path | str,
    docs_dir: Path | str | None = None,
    documents: bool = True,
    state: bool = True,
    ledger: bool = False,
) -> CleanPlan:
    """Calcula qué borrar. No toca el disco."""
    root_path = Path(root).resolve()
    docs = Path(docs_dir) if docs_dir else root_path / "docs" / "generated"
    result = CleanPlan()

    if docs_dir is not None:
        try:
            docs.resolve().relative_to(root_path)
        except ValueError:
            result.warnings.append(f"la salida está fuera del proyecto: {docs}")

    if documents:
        for path in sorted(docs.glob("*.md")) if docs.is_dir() else []:
            if not GENERATED_DOC_RE.match(path.name):
                continue  # documentación escrita a mano: no es de docu
            result.documents.append(path)
        for name in ARTIFACT_DIRS:
            for path in _iter_files(docs / name):
                result.artifacts.append(path)
                if path.suffix.lower() not in (".md", ".mmd", ".txt", ".json", ".html", ".css", ".js", ".svg"):
                    result.warnings.append(f"artefacto con extensión inesperada: {path}")

    state_dir = root_path / STATE_DIR
    if state:
        for name in STATE_FILES:
            candidate = state_dir / name
            if candidate.is_file():
                result.state.append(candidate)
    if ledger:
        candidate = state_dir / LEDGER_FILE
        if candidate.is_file():
            result.ledger.append(candidate)
    return result


def apply(plan_result: CleanPlan) -> tuple[int, list[str]]:
    """Borra lo planificado y devuelve (archivos borrados, errores)."""
    removed = 0
    errors: list[str] = []
    for path in [*plan_result.documents, *plan_result.artifacts, *plan_result.state, *plan_result.ledger]:
        try:
            path.unlink()
            removed += 1
        except OSError as error:
            errors.append(f"{path}: {error}")
    for name in ARTIFACT_DIRS:
        for parent in {path.parent for path in [*plan_result.artifacts]}:
            if parent.name == name:
                try:
                    parent.rmdir()
                except OSError:
                    pass
    return removed, errors


def fingerprint(paths: Sequence[Path]) -> str:
    """Huella corta de una lista de rutas: permite comparar dos planes sin ruido."""
    joined = "\n".join(sorted(str(path) for path in paths))
    return sha256_of(joined)[:12]


__all__ = [
    "ARTIFACT_DIRS",
    "CleanPlan",
    "DOC_SUFFIXES",
    "LEDGER_FILE",
    "STATE_DIR",
    "STATE_FILES",
    "apply",
    "fingerprint",
    "plan",
]
