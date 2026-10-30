"""Intención, decisiones e introducción: prosa derivada de evidencia, no de un modelo.

La diferencia con pedirle a un agente «explicame la intención» es dónde sale el texto:

- **Intención**: de los docstrings y de la documentación que el proyecto ya escribió (README,
  AGENTS.md, CONTRIBUTING). Es lo que el autor quiso decir, no lo que un modelo supone.
- **Decisiones**: de los ADR (`docs/adr/*.md`, `decisions/…`), de los `CHANGELOG` y de los comentarios
  que explican un porqué («porque», «para que», «en lugar de», «decidí», «trade-off»).
- **Introducción**: se compone con plantillas sobre hechos contados, y **cada frase lleva su cita**.
  No es prosa libre: es un párrafo que se puede auditar.

Un agente escribe mejor; esto se puede verificar y se regenera solo. Y cuando el proyecto no tiene
docstrings ni ADRs, el documento lo dice en lugar de inventar una motivación.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from docu.generate.facts import Fact

MAX_INTENT = 40
MAX_DECISIONS = 40
MAX_TEXT = 240

#: Documentos que declaran intención del proyecto antes que del código.
INTENT_DOCS = ("README.md", "AGENTS.md", "CONTRIBUTING.md", "docs/README.md", "LEEME.md")
#: Nombres/rutas donde viven decisiones explícitas.
DECISION_HINTS = ("adr", "decision", "decisiones", "contracts", "fix-", "rfc")

_JAVADOC_RE = re.compile(r"/\*\*(?P<body>.*?)\*/\s*(?P<decl>[A-Za-z@])", re.DOTALL)
_PY_COMMENT_RE = re.compile(r"(?m)^[ \t]*#[ \t]*(?P<text>.+)$")
_CODE_COMMENT_RE = re.compile(r"(?m)^[ \t]*(?://|/\*|\*)[ \t]*(?P<text>.+)$")
_WHY_WORDS = re.compile(
    r"porque|para que|para no|en lugar de|en vez de|sin esto|evita|decid[ií]|decidimos|trade-off|"
    r"motivo|raz[oó]n|elegimos|because|instead of|so that",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(r"(?im)^\s*(?:status|estado)\s*[:=]\s*(?P<status>.+)$")


@dataclass(slots=True)
class Narrative:
    """Lo que el generador pudo decir con evidencia, y lo que no."""

    intent: list[Fact] = field(default_factory=list)
    decisions: list[Fact] = field(default_factory=list)
    intro: str = ""

    @property
    def facts(self) -> list[Fact]:
        return [*self.intent, *self.decisions]


def _clean(text: str) -> str:
    text = re.sub(r"^\s*(?:\*|//|#)\s?", "", text, flags=re.MULTILINE)
    # Fuera imágenes, badges y enlaces sueltos: no son prosa, son decoración del README.
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)", "", text)
    text = re.sub(r"^\s*<[^>]+>\s*$", "", text, flags=re.MULTILINE)
    text = " ".join(text.split())
    # Énfasis de Markdown: `**texto**` es texto, no asteriscos.
    text = re.sub(r"\*\*|__", "", text)
    text = re.sub(r"^[*_>\s]+", "", text)
    text = re.sub(r"[*_]+$", "", text)
    return text.strip()


def _locate(source: str, paragraph: str) -> tuple[int, int]:
    """Línea inicial y final del párrafo en el archivo original.

    El párrafo va normalizado (espacios colapsados), así que buscarlo literal falla: se busca por sus
    primeras palabras tolerando saltos de línea.
    """
    words = paragraph.split()[:6]
    if not words:
        return 1, 1
    pattern = re.compile(r"\s+".join(re.escape(word) for word in words))
    match = pattern.search(source)
    if match is None:
        return 1, 1
    start = _line_of(source, match.start())
    block = re.split(r"\n\s*\n", source[match.start() :], maxsplit=1)[0]
    return start, max(start, start + block.count("\n"))


def _is_prose(text: str) -> bool:
    """¿Esto parece una frase escrita por una persona, o una fila de tabla/una insignia?"""
    if len(text) < 40:
        return False
    if text.startswith(("|", "---", "```", ">")):
        return False
    if text.count("](") >= 1 and not re.search(r"[a-záéíóúñ]{4,}\s+[a-záéíóúñ]{4,}", text):
        return False
    return len(re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", text)) >= 5


def _first_paragraph(text: str) -> str:
    for block in re.split(r"\n\s*\n", text):
        if block.lstrip().startswith("#"):
            continue  # un título no es una declaración de intención
        cleaned = _clean(block)
        if _is_prose(cleaned):
            return cleaned[:MAX_TEXT]
    return ""


def _citation(path: str, start: int, end: int) -> str:
    return f"{path}#L{start}-L{max(start, end)}"


def _line_of(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def doc_facts(rel: str, source: str) -> list[Fact]:
    """Intención (y decisión, si el documento lo es) de un Markdown del proyecto."""
    lines = source.splitlines()
    if not lines:
        return []
    title = next((line.lstrip("# ").strip() for line in lines if line.startswith("#")), "")
    paragraph = _first_paragraph(source)
    if not paragraph:
        return []
    start, end = _locate(source, paragraph)
    facts: list[Fact] = []
    is_decision = any(hint in rel.lower() for hint in DECISION_HINTS)
    status = ""
    for match in _STATUS_RE.finditer(source):
        status = _clean(match.group("status"))[:60]
        break
    if is_decision:
        facts.append(
            Fact(
                kind="decision",
                subject=title or rel,
                detail=f"{status or 'sin estado declarado'} · {paragraph}",
                citation=_citation(rel, start, end),
                attributes={"source": rel, "status": status},
            )
        )
    else:
        facts.append(
            Fact(
                kind="intent",
                subject=title or rel,
                detail=paragraph,
                citation=_citation(rel, start, end),
                attributes={"source": rel},
            )
        )
    return facts


def _javadoc_facts(rel: str, source: str) -> list[Fact]:
    """Docstrings de estilo JSDoc/Javadoc: primer párrafo antes de una declaración."""
    facts: list[Fact] = []
    for match in _JAVADOC_RE.finditer(source):
        paragraph = _first_paragraph(match.group("body"))
        if not paragraph or paragraph.startswith("@"):
            continue
        start = _line_of(source, match.start())
        end = _line_of(source, match.end())
        facts.append(
            Fact(
                kind="intent",
                subject=f"{rel}#L{start}",
                detail=paragraph,
                citation=_citation(rel, start, end),
                attributes={"source": rel},
            )
        )
    return facts


def _python_docstring_facts(rel: str, source: str) -> list[Fact]:
    """Docstrings de módulo, clase y función con `ast`: la intención declarada por el autor."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    facts: list[Fact] = []
    module_doc = ast.get_docstring(tree)
    if module_doc:
        lines = module_doc.strip().splitlines()
        facts.append(
            Fact(
                kind="intent",
                subject=f"{rel} (módulo)",
                detail=_clean(lines[0])[:MAX_TEXT],
                citation=_citation(rel, 1, max(1, len(lines))),
                attributes={"source": rel},
            )
        )
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node)
        if not doc:
            continue
        body = node.body[0] if node.body else node
        start = getattr(body, "lineno", node.lineno)
        end = getattr(node, "end_lineno", node.lineno)
        facts.append(
            Fact(
                kind="intent",
                subject=node.name,
                detail=_clean(doc.strip().splitlines()[0])[:MAX_TEXT],
                citation=_citation(rel, start, min(end, start + 12)),
                attributes={"source": rel},
            )
        )
    return facts


def why_comments(rel: str, source: str) -> list[Fact]:
    """Comentarios que explican un porqué: la decisión queda donde se tomó.

    Sólo se leen **comentarios**, no cadenas ni docstrings: un `#` dentro de una cadena no es una
    decisión del equipo. Esa distinción es la que evita llenar la sección de ruido.
    """
    pattern = _PY_COMMENT_RE if rel.endswith(".py") else _CODE_COMMENT_RE
    facts: list[Fact] = []
    for match in pattern.finditer(source):
        text = _clean(match.group("text")).lstrip(":·- ").strip()
        if len(text) < 40 or not _WHY_WORDS.search(text):
            continue
        line = _line_of(source, match.start())
        facts.append(
            Fact(
                kind="decision",
                subject=text[:60],
                detail=text[:MAX_TEXT],
                citation=_citation(rel, line, line),
                attributes={"source": rel, "status": "comentario en código"},
            )
        )
    return facts


def collect(
    root: Path,
    files: Mapping[str, Path],
    counts: Mapping[str, int],
    project: str,
    read,
) -> Narrative:
    """Recolecta intención y decisiones, y compone la introducción con lo que encontró."""
    collected: list[Fact] = []

    for candidate in INTENT_DOCS + ("CHANGELOG.md",):
        path = root / candidate
        if not path.is_file():
            continue
        try:
            collected.extend(doc_facts(candidate, read(path)))
        except OSError:
            continue

    for rel in sorted(files):
        if not rel.lower().endswith(".md"):
            continue
        if any(hint in rel.lower() for hint in DECISION_HINTS):
            try:
                collected.extend(doc_facts(rel, read(files[rel])))
            except OSError:
                continue

    for rel, path in sorted(files.items()):
        try:
            source = read(path)
        except OSError:
            continue
        if rel.endswith(".py"):
            collected.extend(_python_docstring_facts(rel, source))
            collected.extend(why_comments(rel, source))
        elif rel.endswith((".java", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".jsx")):
            collected.extend(_javadoc_facts(rel, source))
            collected.extend(why_comments(rel, source))

    narrative = Narrative(
        intent=[fact for fact in collected if fact.kind == "intent"][:MAX_INTENT],
        decisions=[fact for fact in collected if fact.kind == "decision"][:MAX_DECISIONS],
    )
    narrative.intro = _intro(project, counts, narrative)
    return narrative


def _short(text: str, limit: int = 44) -> str:
    """Etiqueta legible: sin backticks y cortada en una frontera de palabra."""
    clean = text.replace("", "").strip()
    if len(clean) <= limit:
        return clean
    return clean[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def _intro(project: str, counts: Mapping[str, int], narrative: Narrative) -> str:
    """Introducción legible compuesta de hechos citados, no de adjetivos.

    Cada frase es una afirmación con su fuente: la primera, del conteo real; la segunda, de la
    documentación del proyecto; la tercera, de su propio código. Si falta una fuente, la frase no se
    escribe y la sección lo dice.
    """
    parts: list[str] = []
    modules = counts.get("module", 0)
    packages = counts.get("package", 0)
    routes = counts.get("route", 0)
    types = counts.get("type", 0)
    fields = counts.get("field", 0)

    stack: list[str] = []
    if counts.get("dependency"):
        stack.append(f"{counts['dependency']} dependencias declaradas")
    if modules:
        stack.append(f"{modules} módulos de build")
    if packages:
        stack.append(f"{packages} paquetes")
    if routes:
        stack.append(f"{routes} rutas HTTP")
    if types:
        stack.append(f"{types} tipos y {fields} campos")
    if stack:
        parts.append(f"**{project}** se compone de " + ", ".join(stack) + ".")

    if narrative.intent:
        first = narrative.intent[0]
        parts.append(f"Su propia documentación declara: «{first.detail}» [`{first.citation}`].")
    if narrative.decisions:
        titles = "; ".join(f"«{_short(fact.subject)}»" for fact in narrative.decisions[:3])
        rest = len(narrative.decisions) - len(narrative.decisions[:3])
        extra = f" y {rest} más" if rest > 0 else ""
        parts.append(
            f"El repositorio deja constancia de {len(narrative.decisions)} decisiones "
            f"({titles}{extra}); están listadas con su cita en la sección *Intención y decisiones*."
        )
    if not narrative.intent and not narrative.decisions:
        parts.append(
            "El proyecto **no declara** su intención en docstrings, README ni ADRs: esta sección no "
            "la inventa y queda como hueco hasta que el equipo la escriba."
        )
    return "\n\n".join(parts)


__all__ = [
    "INTENT_DOCS",
    "MAX_DECISIONS",
    "MAX_INTENT",
    "Narrative",
    "collect",
    "doc_facts",
    "why_comments",
]
