"""Capa de prosa delegada: el agente que ya está en el entorno redacta, `docu` valida.

`docu` no incluye un modelo ni pide claves. Emite un **contrato** (`request.json` + `request.md`) con
los hechos citados y las reglas, y acepta un `response.json` escrito por el agente del desarrollador.
Antes de entrar al documento, cada frase se comprueba:

- **Sólo puede hablar de hechos que existan**: cada frase declara los `fact_id` que usa; uno
  desconocido invalida la respuesta.
- **Ninguna cifra nueva**: todo número de la prosa tiene que aparecer en los hechos citados. Es la
  regla que impide el «1.000 de recall» inventado.
- **La estructura es de `docu`, no del modelo**: la prosa no trae encabezados ni listas, sólo párrafos.

Opcional: un **segundo** agente evalúa la prosa con una rúbrica (`judge-request.json`); su veredicto se
ingiere, se guarda en el ledger y, si no llega al umbral, la compuerta pide revisión. La nota del juez
es asesora: la compuerta determinista sigue siendo la que decide.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from docu.generate.facts import Fact

REQUEST_NAME = "prose-request.json"
REQUEST_MARKDOWN = "prose-request.md"
JUDGE_REQUEST = "judge-request.json"
STORE_NAME = "prose.json"
PROSE_DIR = ".docu"

MAX_SENTENCES = 8
MAX_WORDS_PER_SENTENCE = 70
MIN_JUDGE_SCORE = 3.5
NUMBER_RE = re.compile(r"\d[\d.,]*\s*%?")
HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s")

#: Hechos que se ofrecen al redactor, **en orden de prioridad**: primero lo que dice qué es el
#: producto (intención, decisiones, metadatos), después su superficie y sólo al final los detalles.
NARRATIVE_KINDS = (
    "intent", "decision", "doc_section", "route", "module", "package", "dependency", "type", "field"
)
#: Sin estos, una introducción sólo puede enumerar tecnología.
PURPOSE_KINDS = ("intent", "decision", "doc_section")


@dataclass(slots=True)
class ProseResponse:
    """Lo que devolvió el agente redactor, ya validado."""

    reviewer: str = ""
    sections: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return not self.errors and bool(self.sections)


@dataclass(slots=True)
class Verdict:
    """Veredicto de un segundo agente sobre la prosa."""

    judge: str = ""
    score: float = 0.0
    criteria: dict[str, float] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return not self.errors and self.score >= MIN_JUDGE_SCORE


def fact_id(fact: Fact) -> str:
    return f"{fact.kind}:{fact.subject}"


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in text if not unicodedata.combining(char))


def build_request(
    project: str, facts: Sequence[Fact], language: str = "es", limit: int = 120
) -> dict[str, object]:
    """Contrato de redacción: qué puede decir el agente y cómo debe devolverlo."""
    ordered: list[Fact] = []
    for kind in NARRATIVE_KINDS:
        ordered.extend(fact for fact in facts if fact.kind == kind)
        if len(ordered) >= limit:
            break
    selected = ordered[:limit]
    has_purpose = any(fact.kind in PURPOSE_KINDS for fact in facts)
    payload: dict[str, object] = {
        "project": project,
        "language": language,
        "task": (
            "Escribí una introducción breve para este proyecto usando SOLO los hechos listados. "
            "Cada frase debe declarar los ids de los hechos en los que se apoya. No agregues cifras "
            "que no estén en los hechos, no inventes motivaciones y no uses encabezados."
        ),
        "rules": {
            "max_sentences": MAX_SENTENCES,
            "max_words_per_sentence": MAX_WORDS_PER_SENTENCE,
            "must_reference_fact_ids": True,
            "no_new_numbers": True,
            "no_markdown_headings": True,
        },
        "response_schema": {
            "reviewer": "nombre del agente o modelo que redacta",
            "sections": {
                "intro": [
                    {"text": "Una frase.", "fact_ids": ["type:Pedido", "field:Pedido.total"]}
                ]
            },
        },
        "has_purpose_facts": has_purpose,
        "facts": [
            {
                "id": fact_id(fact),
                "kind": fact.kind,
                "subject": fact.subject,
                "detail": fact.detail[:240],
                "citation": fact.citation,
            }
            for fact in selected
        ],
    }
    if not has_purpose:
        payload["warning"] = (
            "no hay hechos que describan el propósito del producto (ni docstring, ni README, ni"
            " description del manifiesto): la introducción sólo podrá ser técnica"
        )
    return payload


def render_request_markdown(request: Mapping[str, object]) -> str:
    """La misma petición en Markdown: para pegarla en un agente conversacional."""
    facts = request.get("facts") or []
    lines = [
        f"# Tarea de redacción · {request.get('project')}",
        "",
        str(request.get("task")),
        "",
        "## Reglas",
        "",
        "- Máximo 8 frases; ninguna de más de 70 palabras.",
        "- **Cada frase declara** los `fact_ids` en los que se apoya.",
        "- **Ninguna cifra** que no esté en los hechos citados.",
        "- Sin encabezados ni listas: sólo párrafos.",
        "",
        "## Hechos disponibles",
        "",
        "| id | detalle | cita |",
        "|---|---|---|",
    ]
    for fact in facts:  # type: ignore[union-attr]
        detail = str(fact["detail"]).replace("|", "\\|")[:200]
        lines.append(f"| `{fact['id']}` | {detail} | `{fact['citation']}` |")
    lines += [
        "",
        "## Formato de respuesta (JSON)",
        "",
        "```json",
        json.dumps(
            {
                "reviewer": "tu nombre o modelo",
                "sections": {
                    "intro": [
                        {"text": "frase", "fact_ids": ["type:Algo"]},
                    ]
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        "```",
        "",
        "Guardalo como `prose-response.json` y aplicá con `docu prose --apply prose-response.json`.",
        "",
    ]
    return "\n".join(lines)


def _numbers(text: str) -> set[str]:
    """Cifras normalizadas: sin espacios, sin `%`, sin puntuación final y con punto decimal.

    `'6,'` (la coma de «Vite 6, escrita») y `'^6.2.3'` tienen que poder compararse: sin esto, el
    validador rechazaba versiones y cantidades que sí estaban en los hechos, y empujaba al redactor a
    omitirlas.
    """
    found: set[str] = set()
    for match in NUMBER_RE.finditer(text):
        token = match.group(0).replace(" ", "").replace("%", "").replace(",", ".")
        token = token.rstrip(".;:")
        if token:
            found.add(token)
    return found


def _number_supported(number: str, supported: set[str]) -> bool:
    """¿La cifra está en los hechos? Igualdad, o prefijo de versión (`19` ⊂ `19.0.1`)."""
    if number in supported:
        return True
    # Prefijo de versión: «Vite 6» contra ^6.2.3, «React 19» contra ^19.0.1.
    return any(candidate.startswith(number + ".") for candidate in supported)


def validate(
    payload: Mapping[str, object], facts: Sequence[Fact]
) -> tuple[ProseResponse, dict[str, Fact]]:
    """Comprueba la respuesta contra los hechos. Nada entra al documento sin pasar por aquí."""
    index = {fact_id(fact): fact for fact in facts}
    response = ProseResponse(reviewer=str(payload.get("reviewer") or ""))
    sections = payload.get("sections")
    if not isinstance(sections, dict) or not sections:
        response.errors.append("la respuesta no trae `sections`")
        return response, index

    for name, sentences in sections.items():
        if not isinstance(sentences, list):
            response.errors.append(f"`sections.{name}` debe ser una lista de frases")
            continue
        if len(sentences) > MAX_SENTENCES:
            response.errors.append(
                f"`sections.{name}` tiene {len(sentences)} frases y el máximo es {MAX_SENTENCES}"
            )
        cleaned: list[dict[str, object]] = []
        for position, sentence in enumerate(sentences, start=1):
            if not isinstance(sentence, dict):
                response.errors.append(f"`{name}` frase {position}: formato inválido")
                continue
            text = str(sentence.get("text") or "").strip()
            ids = sentence.get("fact_ids") or []
            if not text:
                response.errors.append(f"`{name}` frase {position}: texto vacío")
                continue
            if HEADING_RE.search(text):
                response.errors.append(f"`{name}` frase {position}: la prosa no puede traer encabezados")
            if len(text.split()) > MAX_WORDS_PER_SENTENCE:
                response.warnings.append(f"`{name}` frase {position}: supera las 70 palabras")
            unknown = [item for item in ids if item not in index]
            if unknown:
                response.errors.append(
                    f"`{name}` frase {position}: cita hechos inexistentes {unknown[:3]}"
                )
                continue
            if not ids:
                response.warnings.append(
                    f"`{name}` frase {position}: no cita ningún hecho (queda como frase derivada)"
                )
            cited_text = " ".join(
                f"{index[item].subject} {index[item].detail}" for item in ids if item in index
            )
            supported = _numbers(cited_text)
            invented = {
                number for number in _numbers(text) if not _number_supported(number, supported)
            }
            if invented:
                response.errors.append(
                    f"`{name}` frase {position}: cifras sin evidencia {sorted(invented)}"
                )
                continue
            cleaned.append({"text": text, "fact_ids": list(ids)})
        if cleaned:
            response.sections[str(name)] = cleaned
    if not response.sections and not response.errors:
        response.errors.append("la respuesta no aporta ninguna frase válida")
    return response, index


def build_judge_request(
    project: str,
    prose: ProseResponse,
    facts: Sequence[Fact],
    facts_index: Mapping[str, Fact],
) -> dict[str, object]:
    """Rúbrica para que un **segundo** agente evalúe la prosa sin reescribirla."""
    cited: dict[str, dict[str, str]] = {}
    for sentences in prose.sections.values():
        for sentence in sentences:
            for identifier in sentence.get("fact_ids", []):  # type: ignore[union-attr]
                fact = facts_index.get(str(identifier))
                if fact is not None:
                    cited[str(identifier)] = {
                        "detail": fact.detail[:200],
                        "citation": fact.citation,
                    }
    return {
        "project": project,
        "task": (
            "Evaluá la prosa de abajo contra los hechos citados. No la reescribas. Puntuá cada "
            "criterio de 1 a 5 y devolvé el JSON del esquema. Si una frase afirma algo que los hechos "
            "no dicen, marcalo en `issues` y bajá la nota de `fidelidad`."
        ),
        "criteria": {
            "fidelidad": "¿cada frase se sostiene con los hechos citados?",
            "claridad": "¿se entiende sin conocer el código?",
            "utilidad": "¿ayuda a un lector nuevo a ubicarse?",
            "concision": "¿dice lo necesario sin relleno?",
            "tono": "¿es sobrio, sin marketing ni adjetivos vacíos?",
        },
        "threshold": MIN_JUDGE_SCORE,
        "prose": {
            name: [sentence.get("text") for sentence in sentences]
            for name, sentences in prose.sections.items()
        },
        "cited_facts": cited,
        "response_schema": {
            "judge": "nombre del agente o modelo que evalúa",
            "score": "promedio de 1 a 5",
            "criteria": {"fidelidad": 4.0, "claridad": 4.0},
            "issues": ["frase concreta y por qué"],
        },
    }


def load_verdict(payload: Mapping[str, object]) -> Verdict:
    """Ingiere el veredicto del juez, validando forma y rango."""
    verdict = Verdict(judge=str(payload.get("judge") or ""))
    try:
        verdict.score = float(payload.get("score") or 0)
    except (TypeError, ValueError):
        verdict.errors.append("`score` debe ser numérico")
    if verdict.score and not 0 <= verdict.score <= 5:
        verdict.errors.append("`score` debe estar entre 0 y 5")
    criteria = payload.get("criteria")
    if isinstance(criteria, dict):
        for name, value in criteria.items():
            try:
                verdict.criteria[str(name)] = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                verdict.errors.append(f"criterio {name}: valor no numérico")
    issues = payload.get("issues")
    if isinstance(issues, list):
        verdict.issues = [str(item) for item in issues]
    if not verdict.score:
        verdict.errors.append("falta `score`")
    return verdict


def render(prose: ProseResponse, facts_index: Mapping[str, Fact]) -> str:
    """Markdown de la prosa con su procedencia, lista para embeber en el documento."""
    lines = [
        f"> **Prosa redactada por `{prose.reviewer or 'un agente'}`** a partir de hechos citados, y "
        "validada por `docu`: ninguna frase aporta datos nuevos. Las cifras y las tablas de este "
        "documento siguen viniendo de la evidencia, no de la prosa.",
        "",
    ]
    for sentences in prose.sections.values():
        for sentence in sentences:
            citations = [
                f"[`{facts_index[str(identifier)].citation}`]"
                for identifier in sentence.get("fact_ids", [])  # type: ignore[union-attr]
                if str(identifier) in facts_index
            ]
            suffix = f" {' '.join(citations)}" if citations else ""
            lines.append(f"{sentence.get('text')}{suffix}")
            lines.append("")
    return "\n".join(lines)


def store_path(root: Path | str) -> Path:
    return Path(root) / PROSE_DIR / STORE_NAME


def save(root: Path | str, prose: ProseResponse, verdict: Verdict | None = None) -> Path:
    """Persiste la prosa aceptada (y el veredicto, si lo hay) para que `gen` la use."""
    target = store_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "reviewer": prose.reviewer,
        "sections": prose.sections,
        "warnings": prose.warnings,
        "verdict": (
            {
                "judge": verdict.judge,
                "score": verdict.score,
                "criteria": verdict.criteria,
                "issues": verdict.issues,
            }
            if verdict is not None
            else None
        ),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return target


def load(root: Path | str) -> tuple[ProseResponse, Verdict | None] | None:
    """Lee la prosa aceptada, si existe. No revalida: ya se validó al aplicarla."""
    target = store_path(root)
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    sections = payload.get("sections")
    if not isinstance(sections, dict):
        return None
    prose = ProseResponse(
        reviewer=str(payload.get("reviewer") or ""),
        sections={str(name): list(items) for name, items in sections.items()},  # type: ignore[arg-type]
        warnings=[str(item) for item in payload.get("warnings") or []],
    )
    verdict_payload = payload.get("verdict")
    verdict = None
    if isinstance(verdict_payload, dict):
        verdict = Verdict(
            judge=str(verdict_payload.get("judge") or ""),
            score=float(verdict_payload.get("score") or 0),
            criteria={
                str(name): float(value)
                for name, value in (verdict_payload.get("criteria") or {}).items()
            },
            issues=[str(item) for item in verdict_payload.get("issues") or []],
        )
    return prose, verdict


def write_request(directory: Path, request: Mapping[str, object]) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / REQUEST_NAME
    md_path = directory / REQUEST_MARKDOWN
    json_path.write_text(json.dumps(request, ensure_ascii=False, indent=1), encoding="utf-8")
    md_path.write_text(render_request_markdown(request), encoding="utf-8")
    return json_path, md_path


def write_judge_request(directory: Path, request: Mapping[str, object]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / JUDGE_REQUEST
    path.write_text(json.dumps(request, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


__all__ = [
    "JUDGE_REQUEST",
    "MAX_SENTENCES",
    "MIN_JUDGE_SCORE",
    "PROSE_DIR",
    "ProseResponse",
    "REQUEST_MARKDOWN",
    "REQUEST_NAME",
    "STORE_NAME",
    "Verdict",
    "build_judge_request",
    "build_request",
    "fact_id",
    "load",
    "load_verdict",
    "render",
    "render_request_markdown",
    "save",
    "store_path",
    "validate",
    "write_judge_request",
    "write_request",
]
