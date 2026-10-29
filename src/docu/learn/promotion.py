"""Decisión de promoción: sin compuerta, el aprendizaje es una forma lenta de romper cosas.

Un candidato solo sustituye al patrón vigente si mejora de forma medible **y** no degrada ninguna
métrica vigilada más allá del umbral de reversión. Las dos reglas son datos del perfil, no constantes
escondidas en el código.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from docu.learn.patterns import WATCHED, Pattern

PROMOTE = "promote"
REJECT = "reject"
ROLLBACK = "rollback"


@dataclass(frozen=True, slots=True)
class Decision:
    action: str
    pattern_id: str
    delta: float
    reasons: Sequence[str] = field(default_factory=tuple)

    @property
    def is_change(self) -> bool:
        return self.action in (PROMOTE, ROLLBACK)

    def describe(self) -> str:
        detail = "; ".join(self.reasons) if self.reasons else "sin detalle"
        return f"{self.action.upper()} {self.pattern_id} (Δ medio {self.delta:+.3f}): {detail}"


def _average(metrics: dict[str, float], names: Sequence[str] = WATCHED) -> float:
    values = [metrics.get(name, 0.0) for name in names if name in metrics]
    return sum(values) / len(values) if values else 0.0


def decide(
    current: Pattern | None,
    candidate: Pattern,
    *,
    promotion_delta: float = 0.05,
    rollback_drop: float = 0.05,
) -> Decision:
    """Compara candidato y vigente. Nunca modifica nada: solo decide y explica por qué."""
    if current is None:
        return Decision(
            action=PROMOTE,
            pattern_id=candidate.pattern_id,
            delta=_average(dict(candidate.metrics)),
            reasons=("no había patrón vigente para este stack",),
        )

    deltas = {
        name: round(candidate.metrics.get(name, 0.0) - current.metrics.get(name, 0.0), 3)
        for name in WATCHED
        if name in candidate.metrics or name in current.metrics
    }
    mean_delta = round(sum(deltas.values()) / len(deltas), 3) if deltas else 0.0
    drops = {name: value for name, value in deltas.items() if value < -rollback_drop}

    if drops:
        detail = ", ".join(f"{name} {value:+.3f}" for name, value in sorted(drops.items()))
        return Decision(
            action=ROLLBACK,
            pattern_id=candidate.pattern_id,
            delta=mean_delta,
            reasons=(f"degrada {detail} (umbral -{rollback_drop:.2f})",),
        )
    if mean_delta >= promotion_delta:
        beste = max(deltas.items(), key=lambda item: item[1]) if deltas else ("—", 0.0)
        return Decision(
            action=PROMOTE,
            pattern_id=candidate.pattern_id,
            delta=mean_delta,
            reasons=(
                f"mejora media {mean_delta:+.3f} ≥ {promotion_delta:.2f}",
                f"mayor avance en {beste[0]} ({beste[1]:+.3f})",
            ),
        )
    return Decision(
        action=REJECT,
        pattern_id=candidate.pattern_id,
        delta=mean_delta,
        reasons=(f"mejora {mean_delta:+.3f} < {promotion_delta:.2f}",),
    )


__all__ = ["Decision", "PROMOTE", "REJECT", "ROLLBACK", "decide"]
