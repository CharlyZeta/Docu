"""Codigos de salida estables: el CI decide sin parsear texto."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    NO_CHANGES = 10          # nada que regenerar: exito silencioso
    NEEDS_REVIEW = 20        # compuerta de calidad abierta: hay que mirar
    BUDGET_EXHAUSTED = 30    # se agoto presupuesto: entrega parcial
    UNCITABLE_SOURCE = 40    # fuente volatil sin snapshot
    NOT_IMPLEMENTED = 50     # fase aun no construida (scaffold)
    CONFIG_ERROR = 60        # perfil invalido o ausente
    INTERNAL_ERROR = 70      # bug del motor
