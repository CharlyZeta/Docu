"""Federación opt-in: compartir aprendizaje sin compartir el cliente.

Regla de privacidad, verificada por test: el payload solo lleva **huellas y métricas**. Nunca
nombres de proyecto, rutas, contenido de código ni texto de documentación. Un patrón se identifica
por hash, no por nombre.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Sequence

from docu.core.contracts import utcnow, sha256_of
from docu.learn.patterns import PatternLibrary

SCHEMA_VERSION = "1.0"
MAX_PATTERNS = 50

#: Únicas claves permitidas en el payload federado. Cualquier otra es una fuga.
ALLOWED_KEYS = frozenset(
    {"schema_version", "generated_at", "docu_version", "patterns", "metrics", "runs", "stack", "fingerprint", "kind"}
)


class FederationError(RuntimeError):
    """El payload no cumple la política de privacidad: se rechaza el envío."""


@dataclass(frozen=True, slots=True)
class FederationPayload:
    data: Mapping[str, object]

    def to_json(self) -> str:
        return json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True)


def fingerprint(value: str) -> str:
    """Huella estable y no reversible del identificador del patrón."""
    return "fp_" + sha256_of(value).replace("sha256:", "")[:16]


def build_payload(
    library: PatternLibrary,
    *,
    docu_version: str = "0.1.0",
    limit: int = MAX_PATTERNS,
) -> FederationPayload:
    """Construye el payload mínimo: stack, métricas y corridas. Ni un dato del cliente."""
    patterns = []
    for pattern in list(library.patterns.values())[:limit]:
        patterns.append(
            {
                "fingerprint": fingerprint(pattern.pattern_id),
                "stack": pattern.stack,
                "kind": pattern.kind,
                "metrics": {name: round(float(value), 3) for name, value in pattern.metrics.items()},
                "runs": pattern.runs,
            }
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utcnow().isoformat(timespec="seconds"),
        "docu_version": docu_version,
        "patterns": patterns,
    }
    assert_anonymous(payload)
    return FederationPayload(data=payload)


def assert_anonymous(payload: Mapping[str, object]) -> None:
    """Comprueba la política. Falla ruidosamente: es mejor no enviar que filtrar."""
    _check_keys(payload)
    serialized = json.dumps(payload, ensure_ascii=False)
    lowered = serialized.lower()
    for leak in (":\\", "src/", "c:\\", ".java", ".py", ".ts", "http://", "https://", "@"):
        if leak in lowered:
            raise FederationError(f"el payload contiene algo que parece una ruta o contacto: {leak!r}")


def _check_keys(node: object) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key not in ALLOWED_KEYS:
                raise FederationError(f"clave no permitida en el payload: {key!r}")
            if key == "metrics":
                # Los nombres de métrica son vocabulario del producto, no datos del cliente;
                # lo que se exige es que sus valores sean números.
                if not isinstance(value, dict):
                    raise FederationError("'metrics' debe ser un mapa de números")
                for metric_name, metric_value in value.items():
                    if not isinstance(metric_value, (int, float)) or isinstance(metric_value, bool):
                        raise FederationError(f"métrica no numérica en el payload: {metric_name!r}")
                continue
            _check_keys(value)
    elif isinstance(node, list):
        for item in node:
            _check_keys(item)


def preview(payload: FederationPayload) -> str:
    """Vista previa obligatoria antes de enviar: lo que el usuario ve es lo que sale."""
    return payload.to_json()


def send(
    payload: FederationPayload,
    endpoint: str | None,
    *,
    dry_run: bool = True,
    timeout: float = 10.0,
) -> dict[str, object]:
    """Envía el payload si hay endpoint y no es dry-run. Sin endpoint, solo devuelve el resumen."""
    assert_anonymous(payload.data)
    if dry_run or not endpoint:
        return {
            "sent": False,
            "reason": "dry-run" if dry_run else "sin endpoint configurado",
            "patterns": len(payload.data.get("patterns") or []),  # type: ignore[arg-type]
        }
    if not endpoint.startswith(("http://", "https://")):
        raise FederationError("el endpoint debe ser http(s)")

    request = urllib.request.Request(
        endpoint,
        data=payload.to_json().encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - endpoint explicito
            status = response.status
    except (urllib.error.URLError, OSError) as error:
        return {"sent": False, "reason": f"error de red: {error}"}
    return {"sent": True, "status": status}


__all__ = [
    "ALLOWED_KEYS",
    "FederationError",
    "FederationPayload",
    "assert_anonymous",
    "build_payload",
    "fingerprint",
    "preview",
    "send",
]
