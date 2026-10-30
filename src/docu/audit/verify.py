"""Auditoría determinista de la documentación generada.

**No usa ningún modelo.** Cada comprobación es código que se puede volver a ejecutar y da el mismo
resultado: es la diferencia entre una compuerta y una opinión. Un juez LLM puede añadir después una
nota sobre claridad o utilidad, pero nunca puede sustituir estas cinco comprobaciones — y si las
sustituyera, el producto perdería exactamente lo que promete: trazabilidad verificable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from docu.core.contracts import DocState
from docu.core.profile import find, load
from docu.generate.facts import Fact
from docu.generate.pipeline import (
    applicability,
    collect_facts,
    completeness,
    inspect,
)

CITATION_RE = re.compile(r"(.+?)#L(\d+)-L(\d+)$")
PATH_CELL_RE = re.compile(r"`(/[^`]*)`")
LEVEL_PREFIX = re.compile(r"^l(\d)-")

#: Peso de cada comprobación en la nota final (suma 100).
WEIGHTS = {
    "citations": 40,
    "duplicates": 10,
    "consistency": 25,
    "coverage": 15,
    "freshness": 10,
}


@dataclass(frozen=True, slots=True)
class Check:
    """Resultado de una comprobación."""

    name: str
    total: int
    failed: int
    details: tuple[str, ...] = ()
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.failed == 0

    @property
    def score(self) -> float:
        if self.total == 0:
            return 0.0 if self.failed else 100.0
        return 100.0 * (self.total - self.failed) / self.total

    def to_dict(self) -> dict[str, object]:
        return {
            "check": self.name,
            "total": self.total,
            "failed": self.failed,
            "passed": self.passed,
            "score": round(self.score, 2),
            "note": self.note,
            "details": list(self.details),
        }


@dataclass(slots=True)
class AuditReport:
    project: str
    checks: dict[str, Check] = field(default_factory=dict)

    @property
    def score(self) -> float:
        total = sum(WEIGHTS[name] for name in self.checks)
        if not total:
            return 0.0
        return round(
            sum(WEIGHTS[name] * check.score for name, check in self.checks.items()) / total, 2
        )

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks.values())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "project": self.project,
            "score": self.score,
            "passed": self.passed,
            "weights": WEIGHTS,
            "checks": {name: check.to_dict() for name, check in self.checks.items()},
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Auditoría de documentación · {self.project}",
            "",
            f"Nota: **{self.score:.2f}/100** · {'sin hallazgos' if self.passed else 'con hallazgos'}",
            "",
            "| Comprobación | Peso | Resultado | Fallos | Detalle |",
            "|---|---|---|---|---|",
        ]
        for name, check in self.checks.items():
            mark = "✔" if check.passed else "✖"
            lines.append(
                f"| `{name}` | {WEIGHTS[name]} | {mark} {check.score:.0f}% | "
                f"{check.failed}/{check.total} | {check.note} |"
            )
        lines += ["", "## Hallazgos", ""]
        any_detail = False
        for name, check in self.checks.items():
            for detail in check.details:
                any_detail = True
                lines.append(f"- **{name}**: {detail}")
        if not any_detail:
            lines.append("_Ninguno._")
        lines.append("")
        return "\n".join(lines)


# --------------------------------------------------------------------------- comprobaciones


def check_citations(facts: Sequence[Fact], root: Path) -> Check:
    """Cada cita debe apuntar a un archivo existente, a un rango válido y contener su sujeto.

    Es la comprobación que sostiene la promesa del producto: si una cita no se puede abrir y
    confirmar, el documento no vale más que uno sin citas.
    """
    cache: dict[str, list[str] | None] = {}
    failed = 0
    details: list[str] = []
    for fact in facts:
        match = CITATION_RE.match(fact.citation)
        if match is None:
            failed += 1
            details.append(f"{fact.subject}: cita sin formato `ruta#Lx-Ly` ({fact.citation!r})")
            continue
        path, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        if path not in cache:
            target = root / path
            cache[path] = (
                target.read_text(encoding="utf-8", errors="replace").splitlines()
                if target.exists()
                else None
            )
        lines = cache[path]
        if lines is None:
            failed += 1
            details.append(f"{fact.subject}: archivo inexistente {path}")
            continue
        if not lines and (start, end) == (1, 1):
            # Archivo vacío (`__init__.py`): la afirmación es «este paquete existe» y la evidencia
            # es la existencia del archivo. Citar L1-L1 es una convención explícita, no un error.
            continue
        if start < 1 or end > len(lines):
            failed += 1
            details.append(f"{fact.subject}: rango {start}-{end} fuera de {path} ({len(lines)} líneas)")
            continue
        span = "\n".join(lines[start - 1 : end]).lower()
        if not all(probe.lower() in span for probe in _probes(fact)):
            failed += 1
            details.append(f"{fact.subject}: el sujeto no aparece en {fact.citation}")
    return Check("citations", len(facts), failed, tuple(details[:20]), "archivo, rango y sujeto")


def _probes(fact: Fact) -> list[str]:
    """Qué debe aparecer en el rango citado para considerar la afirmación sostenida."""
    subject = fact.subject
    if fact.kind == "route":
        verb, _, path = subject.partition(" ")
        return [path] if verb == "ANY" else [verb, path]
    if fact.kind in ("method", "type"):
        return [subject.rsplit(".", 1)[-1]]
    if fact.kind == "dependency":
        return [subject.split(":")[-1]]
    if fact.kind == "config_key":
        return [subject.split(".")[-1]]
    if fact.kind in ("package", "module", "parent", "plugin"):
        return []  # la evidencia es el archivo declarante, ya verificado arriba
    return [subject.rsplit(".", 1)[-1]]


def check_duplicates(facts: Sequence[Fact]) -> Check:
    """Una afirmación repetida **con la misma prueba** es ruido, no documentación.

    El par (sujeto, cita) es la unidad: el mismo `uses` en dos pasos de un workflow YAML comparte
    ruta aplanada pero vive en líneas distintas, así que no es duplicado.
    """
    seen: dict[tuple[str, str, str], int] = {}
    for fact in facts:
        key = (fact.kind, fact.subject, fact.citation)
        seen[key] = seen.get(key, 0) + 1
    repeated = {key: count for key, count in seen.items() if count > 1}
    details = [
        f"{kind} {subject!r} aparece {count} veces en {citation}"
        for (kind, subject, citation), count in repeated.items()
    ]
    return Check("duplicates", len(facts), len(repeated), tuple(details[:20]), "afirmaciones repetidas")


def _document_paths(text: str) -> set[str]:
    """Rutas HTTP documentadas en las tablas de un nivel."""
    return {match.group(1) for match in PATH_CELL_RE.finditer(text)}


def check_consistency(docs: Mapping[str, str]) -> Check:
    """El mismo hecho no puede diferir entre niveles: es el fallo que la guía llama deriva interna."""
    if len(docs) < 2:
        return Check("consistency", 0, 0, (), "un solo nivel generado: nada que contrastar")
    paths = {level: _document_paths(text) for level, text in docs.items()}
    reference_level = sorted(paths)[0]
    reference = paths[reference_level]
    failed = 0
    details: list[str] = []
    for level, found in paths.items():
        if level == reference_level:
            continue
        for missing in sorted(reference - found):
            failed += 1
            details.append(f"{missing} está en {reference_level} y no en {level}")
    total = sum(len(value) for value in paths.values())
    return Check("consistency", total, failed, tuple(details[:20]), "rutas coherentes entre niveles")


def check_coverage(facts: Sequence[Fact], root: Path) -> Check:
    """Secciones aplicables que quedaron sin evidencia."""
    applicable = applicability(facts, root)
    required = [kind for kind, needed in applicable.items() if needed]
    missing = [
        kind
        for kind in required
        if not any(fact.kind in _evidence_kinds(kind) for fact in facts)
    ]
    details = [f"sección aplicable sin evidencia: {kind}" for kind in missing]
    return Check("coverage", len(required), len(missing), tuple(details), "secciones aplicables")


def _evidence_kinds(kind: str) -> tuple[str, ...]:
    if kind == "module":
        return ("module", "package")
    return (kind,)


def check_freshness(
    root: Path,
    levels: Sequence[str],
    manifest_path: Path | str | None = None,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    ttl_days: int = 90,
) -> Check:
    """Estado del manifest: un documento desactualizado no es documentación, es historia.

    El descubrimiento debe ser **el mismo** que usó la generación. Si no, los hashes no coinciden y
    la auditoría inventa páginas obsoletas.
    """
    manifest, states, _hashes = inspect(
        root,
        levels=levels,
        manifest_path=manifest_path,
        include=include,
        exclude=exclude,
        ttl_days=ttl_days,
    )
    stale = [
        f"{level}: {state.value}" for level, state in states.items() if state is not DocState.FRESH
    ]
    return Check(
        "freshness",
        len(states),
        len(stale),
        tuple(stale),
        "sin manifest" if manifest is None else "estados del manifest",
    )


# --------------------------------------------------------------------------- entrada


def audit(
    root: Path | str,
    docs_dir: Path | str | None = None,
    levels: Sequence[str] = ("l1", "l4"),
    profile_path: Path | str | None = None,
    include_tests: bool = False,
) -> AuditReport:
    """Ejecuta las cinco comprobaciones. Sin modelos, sin red, sin coste."""
    root_path = Path(root).resolve()
    profile = load(profile_path) if profile_path else (
        load(find(root_path)) if find(root_path) else None
    )
    exclude = profile.effective_exclude if profile else ()
    include = profile.include if profile else ()
    facts, _sources = collect_facts(
        root_path, include_tests=include_tests, include=include, exclude=exclude
    )

    target = Path(docs_dir) if docs_dir else root_path / "docs" / "generated"
    documents: dict[str, str] = {}
    if target.exists():
        for path in sorted(target.glob("*.md")):
            match = LEVEL_PREFIX.match(path.name)
            level = f"l{match.group(1)}" if match else path.stem
            documents[level] = path.read_text(encoding="utf-8")

    # El nombre documentado vive en el manifest; el del directorio es un fallback.
    from docu.index.manifest import Manifest
    from docu.generate.pipeline import manifest_file

    manifest = Manifest.load(manifest_file(root_path, None))
    project_name = (
        (profile.project if profile and profile.project else None)
        or (manifest.project if manifest is not None else None)
        or root_path.name
    )
    report = AuditReport(project=project_name)
    report.checks["citations"] = check_citations(facts, root_path)
    report.checks["duplicates"] = check_duplicates(facts)
    report.checks["consistency"] = check_consistency(documents)
    report.checks["coverage"] = check_coverage(facts, root_path)
    report.checks["freshness"] = check_freshness(
        root_path,
        levels,
        include=include,
        exclude=exclude,
        ttl_days=profile.ttl_days if profile else 90,
    )
    return report


__all__ = [
    "AuditReport",
    "Check",
    "WEIGHTS",
    "audit",
    "check_citations",
    "check_consistency",
    "check_coverage",
    "check_duplicates",
    "check_freshness",
]
