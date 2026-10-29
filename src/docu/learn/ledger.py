"""Ledger local: la memoria de cada corrida.

Sin registro no hay aprendizaje, solo impresiones. Cada ejecución deja una línea con métricas,
versiones, compuerta y coste; el resto del sistema (patrones, promoción, federación) se deriva de
aquí. El ledger es del proyecto, no del fabricante: vive en `.docu/ledger.jsonl`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from docu.core.contracts import GateDecision, GateOutcome, Metrics, Mode, RunRecord, utcnow

LEDGER_PATH = ".docu/ledger.jsonl"


def ledger_file(root: Path | str, explicit: Path | str | None = None) -> Path:
    return Path(explicit) if explicit else Path(root) / LEDGER_PATH


def new_run_id(now: datetime | None = None) -> str:
    moment = now or utcnow()
    return f"run-{moment.strftime('%Y%m%dT%H%M%S')}-{int(moment.microsecond / 1000):03d}"


def append(
    path: Path | str,
    *,
    project: str,
    metrics: Metrics,
    gate: GateDecision,
    mode: Mode = Mode.APPLY,
    states: Mapping[str, str] | None = None,
    versions: Mapping[str, str] | None = None,
    pages_written: int = 0,
    pages_skipped: int = 0,
    elapsed_s: float = 0.0,
    commit: str | None = None,
    errors: Sequence[str] = (),
) -> RunRecord:
    """Registra una corrida. Nunca lanza: un ledger roto no puede tumbar la generación."""
    started = utcnow()
    record = RunRecord(
        run_id=new_run_id(started),
        project=project,
        commit=commit,
        mode=mode,
        started_at=started,
        finished_at=started,
        versions={**(versions or {}), "states": ",".join(f"{k}={v}" for k, v in sorted((states or {}).items()))},
        metrics=metrics,
        gate=gate,
        pages_written=pages_written,
        pages_skipped=pages_skipped,
        cost_usd=metrics.cost_usd,
        errors=list(errors),
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(record.to_jsonl() + "\n")
    return record


def load(path: Path | str) -> list[dict[str, object]]:
    """Lee el ledger tolerando lineas corruptas: se descartan, no se interpretan."""
    target = Path(path)
    if not target.exists():
        return []
    records: list[dict[str, object]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _metric(record: Mapping[str, object], name: str) -> float | None:
    metrics = record.get("metrics")
    if not isinstance(metrics, dict):
        return None
    value = metrics.get(name)
    return float(value) if isinstance(value, (int, float)) else None


def summarize(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Resumen agregado: corridas, medias por metrica, ultima corrida y tasa de bloqueo."""
    if not records:
        return {"runs": 0, "metrics": {}, "aborted": 0, "projects": []}

    names = ("accuracy", "completeness", "attribution", "conciseness", "freshness", "cost_usd")
    averages: dict[str, float] = {}
    for name in names:
        values = [value for record in records if (value := _metric(record, name)) is not None]
        if values:
            averages[name] = round(sum(values) / len(values), 3)

    aborted = sum(
        1
        for record in records
        if isinstance(record.get("gate"), dict)
        and record["gate"].get("outcome") == GateOutcome.ABORT.value  # type: ignore[union-attr]
    )
    last = records[-1]
    return {
        "runs": len(records),
        "metrics": averages,
        "aborted": aborted,
        "projects": sorted({str(record.get("project")) for record in records if record.get("project")}),
        "last_run": {
            "run_id": last.get("run_id"),
            "project": last.get("project"),
            "started_at": last.get("started_at"),
            "outcome": (last.get("gate") or {}).get("outcome") if isinstance(last.get("gate"), dict) else None,
        },
    }


def outcome_counts(records: Iterable[Mapping[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        gate = record.get("gate")
        outcome = gate.get("outcome") if isinstance(gate, dict) else None
        key = str(outcome or "desconocido")
        counts[key] = counts.get(key, 0) + 1
    return counts


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


__all__ = [
    "LEDGER_PATH",
    "append",
    "ledger_file",
    "load",
    "new_run_id",
    "outcome_counts",
    "parse_timestamp",
    "summarize",
]
