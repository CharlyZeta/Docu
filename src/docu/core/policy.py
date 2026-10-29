"""Politica del agente: modos, presupuestos y compuertas.

Aqui vive la respuesta a "que hace el agente solo y cuando se detiene". Es logica pura y
testeable: ninguna decision de publicacion puede saltarse `evaluate()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from docu.core.contracts import GateDecision, GateOutcome, Metrics, Mode


class BudgetExhausted(RuntimeError):
    """Se agoto un presupuesto: la corrida entrega lo completo y deja `pending`, no texto degradado."""


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Umbrales **por metrica**. Un unico umbral para cuatro metricas distintas es un error de diseno."""

    accuracy: float = 8.5
    completeness: float = 9.0
    attribution: float = 9.5
    conciseness: float = 7.5

    def as_mapping(self) -> Mapping[str, float]:
        return {
            "accuracy": self.accuracy,
            "completeness": self.completeness,
            "attribution": self.attribution,
            "conciseness": self.conciseness,
        }


@dataclass(slots=True)
class Budget:
    """Presupuesto por corrida. `spend()` lanza cuando se agota: fallar rapido y limpio."""

    max_cost_usd: float = 3.0
    max_seconds: float = 900.0
    max_pages: int = 40
    max_llm_calls: int = 120
    spent_usd: float = 0.0
    elapsed_s: float = 0.0
    pages_written: int = 0
    llm_calls: int = 0

    def spend(self, *, usd: float = 0.0, seconds: float = 0.0, pages: int = 0, calls: int = 0) -> None:
        self.spent_usd += usd
        self.elapsed_s += seconds
        self.pages_written += pages
        self.llm_calls += calls
        if self.exceeded():
            raise BudgetExhausted("; ".join(self.exceeded()))

    def exceeded(self) -> list[str]:
        problems: list[str] = []
        if self.spent_usd > self.max_cost_usd:
            problems.append(f"coste {self.spent_usd:.2f} > {self.max_cost_usd:.2f} USD")
        if self.elapsed_s > self.max_seconds:
            problems.append(f"tiempo {self.elapsed_s:.0f}s > {self.max_seconds:.0f}s")
        if self.pages_written > self.max_pages:
            problems.append(f"paginas {self.pages_written} > {self.max_pages}")
        if self.llm_calls > self.max_llm_calls:
            problems.append(f"llamadas {self.llm_calls} > {self.max_llm_calls}")
        return problems

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.max_cost_usd - self.spent_usd)


@dataclass(frozen=True, slots=True)
class GatePolicy:
    """Reglas de aprobacion. Las puertas duras no se negocian por metrica."""

    thresholds: Thresholds = field(default_factory=Thresholds)
    require_zero_unsupported: bool = True
    require_fresh: bool = True

    def evaluate(self, metrics: Metrics, mode: Mode) -> GateDecision:
        reasons: list[str] = []

        # Puertas duras: cualquier violacion aborta la publicacion (no la corrida).
        if self.require_zero_unsupported and metrics.unsupported_claims > 0:
            reasons.append(f"{metrics.unsupported_claims} afirmaciones sin evidencia")
        if self.require_fresh and metrics.freshness < 10.0:
            reasons.append(f"frescura {metrics.freshness:.1f}/10")

        # Puertas de umbral: por debajo se abre revision, no se publica.
        for name, floor in self.thresholds.as_mapping().items():
            value = getattr(metrics, name)
            if value < floor:
                reasons.append(f"{name} {value:.1f} < {floor:.1f}")

        if mode is Mode.PROPOSE:
            return GateDecision(GateOutcome.REVIEW, tuple(reasons) or ("modo propose: revisar diff",))
        if reasons:
            hard = self.require_zero_unsupported and metrics.unsupported_claims > 0
            hard = hard or (self.require_fresh and metrics.freshness < 10.0)
            return GateDecision(GateOutcome.ABORT if hard else GateOutcome.REVIEW, tuple(reasons))
        return GateDecision(GateOutcome.PUBLISH, ())
