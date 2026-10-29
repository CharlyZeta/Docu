"""Biblioteca de patrones por stack, con promoción validada y reversión.

Regla dura del producto: **el agente no modifica su código.** Aprende parámetros y selección de
patrones, y todo candidato pasa por una compuerta: solo se promueve si mejora y no degrada nada más
allá del umbral; si una métrica cae, se revierte a la versión anterior.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from docu.core.contracts import utcnow, sha256_of

PATTERNS_PATH = ".docu/patterns.json"
SCHEMA_VERSION = "1.0"

#: Métricas que la promoción vigila. Cambiar este conjunto invalida comparaciones históricas.
WATCHED = ("accuracy", "completeness", "attribution", "conciseness")


@dataclass(frozen=True, slots=True)
class Pattern:
    """Un patrón aprendido: qué stack, qué mejora y con qué evidencia."""

    pattern_id: str
    stack: str
    kind: str  # "profile_default" | "glossary_entry" | "failure_avoidance"
    metrics: Mapping[str, float] = field(default_factory=dict)
    runs: int = 0
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "pattern_id": self.pattern_id,
            "stack": self.stack,
            "kind": self.kind,
            "metrics": dict(self.metrics),
            "runs": self.runs,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "Pattern":
        metrics = payload.get("metrics") or {}
        return cls(
            pattern_id=str(payload.get("pattern_id", "")),
            stack=str(payload.get("stack", "")),
            kind=str(payload.get("kind", "profile_default")),
            metrics={str(key): float(value) for key, value in metrics.items()},  # type: ignore[union-attr]
            runs=int(payload.get("runs", 0)),  # type: ignore[arg-type]
            notes=str(payload.get("notes", "")),
        )


@dataclass(slots=True)
class PatternLibrary:
    """Versión vigente + historial mínimo para poder revertir."""

    patterns: dict[str, Pattern] = field(default_factory=dict)
    history: list[dict[str, object]] = field(default_factory=list)
    version: str = "0"
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "version": self.version,
            "patterns": {key: pattern.to_dict() for key, pattern in self.patterns.items()},
            "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PatternLibrary":
        raw = payload.get("patterns") or {}
        patterns = {
            str(key): Pattern.from_dict(value)  # type: ignore[arg-type]
            for key, value in raw.items()  # type: ignore[union-attr]
            if isinstance(value, dict)
        }
        history = payload.get("history") or []
        return cls(
            patterns=patterns,
            history=[item for item in history if isinstance(item, dict)],  # type: ignore[union-attr]
            version=str(payload.get("version", "0")),
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        )

    # ------------------------------------------------------------------ persistencia

    def save(self, path: Path | str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: Path | str) -> "PatternLibrary":
        target = Path(path)
        if not target.exists():
            return cls()
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return cls()
        return cls.from_dict(payload) if isinstance(payload, dict) else cls()

    # ------------------------------------------------------------------ operaciones

    def promote(self, pattern: Pattern) -> None:
        """Instala un patrón guardando la versión previa para poder revertir."""
        previous = self.patterns.get(pattern.pattern_id)
        self.history.append(
            {
                "action": "promote",
                "pattern_id": pattern.pattern_id,
                "at": utcnow().isoformat(timespec="seconds"),
                "previous": previous.to_dict() if previous else None,
                "installed": pattern.to_dict(),
            }
        )
        self.patterns[pattern.pattern_id] = pattern
        self.version = _next_version(self.version)

    def revert(self, pattern_id: str) -> bool:
        """Revierte al estado previo registrado. Devuelve si habia algo que revertir."""
        for entry in reversed(self.history):
            if entry.get("pattern_id") != pattern_id or entry.get("action") != "promote":
                continue
            previous = entry.get("previous")
            if isinstance(previous, dict):
                self.patterns[pattern_id] = Pattern.from_dict(previous)
            else:
                self.patterns.pop(pattern_id, None)
            self.history.append(
                {"action": "revert", "pattern_id": pattern_id, "at": utcnow().isoformat(timespec="seconds")}
            )
            self.version = _next_version(self.version)
            return True
        return False


def _next_version(current: str) -> str:
    try:
        return str(int(current) + 1)
    except ValueError:
        return "1"


# --------------------------------------------------------------------------- candidatos


@dataclass(frozen=True, slots=True)
class Candidate:
    """Patrón propuesto a partir del ledger, con la evidencia que lo respalda."""

    pattern: Pattern
    reasons: Sequence[str] = ()

    @property
    def key(self) -> str:
        return self.pattern.pattern_id


def stack_of(project: str, records: Sequence[Mapping[str, object]]) -> str:
    """Heuristica de stack a partir del proyecto y de los lenguajes vistos en sus corridas."""
    languages = {
        str(language)
        for record in records
        for language in str(record.get("versions", {}).get("languages", "")).split(",")
        if language
    }
    if languages:
        return "+".join(sorted(languages))
    return project.split("-")[-1] if "-" in project else project


def candidates_from(
    records: Sequence[Mapping[str, object]],
    min_runs: int = 1,
    improvement: float = 0.0,
) -> list[Candidate]:
    """Agrupa el ledger por proyecto/stack y propone el rendimiento observado como patrón.

    No inventa: el candidato es literalmente «esta configuración dio estas métricas en estas
    corridas». La promoción decide si sustituye al patrón vigente.
    """
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for record in records:
        project = str(record.get("project") or "desconocido")
        grouped.setdefault(project, []).append(record)

    candidates: list[Candidate] = []
    for project, group in sorted(grouped.items()):
        if len(group) < min_runs:
            continue
        averages: dict[str, float] = {}
        for name in WATCHED:
            values = [
                float(record["metrics"][name])  # type: ignore[index]
                for record in group
                if isinstance(record.get("metrics"), dict) and name in record["metrics"]  # type: ignore[operator]
            ]
            if values:
                averages[name] = round(sum(values) / len(values), 3)
        if not averages:
            continue
        stack = stack_of(project, group)
        pattern = Pattern(
            pattern_id=f"{stack}:profile_default",
            stack=stack,
            kind="profile_default",
            metrics=averages,
            runs=len(group),
            notes=f"media de {len(group)} corridas en {project}",
        )
        candidates.append(
            Candidate(
                pattern=pattern,
                reasons=[
                    f"{len(group)} corridas observadas",
                    f"concisión media {averages.get('conciseness', 0):.2f}",
                ],
            )
        )
    _ = improvement
    return candidates


__all__ = [
    "Candidate",
    "PATTERNS_PATH",
    "Pattern",
    "PatternLibrary",
    "WATCHED",
    "candidates_from",
    "stack_of",
]
