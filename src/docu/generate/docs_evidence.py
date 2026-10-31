"""La documentación que el proyecto ya escribió, como evidencia citada.

Hallazgo F-06 de la prueba externa: el `l4` declaraba «Prerrequisitos» y «Puesta en marcha» como
huecos **teniendo un README de 34 KB que los explicaba**. No es una contradicción menor: es el
documento de onboarding sin la información que el onboarding necesita.

La regla que no cambia: una sección del README no es una afirmación del generador. Se cita como
**documentación existente**, aparte de los hechos de código, y si no hay sección que corresponda el
hueco sigue declarado. Docu no copia prosa: enlaza y cita el párrafo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from docu.generate.facts import Fact

MAX_SECTIONS = 60
MAX_TEXT = 400

#: Archivos donde un proyecto escribe cómo se instala y cómo se arranca.
DOC_FILES = ("README.md", "LEEME.md", "AGENTS.md", "CONTRIBUTING.md", "INSTALL.md", "docs/README.md")
DOC_DIRS = ("docs", "documentation")

_HEADING_RE = re.compile(r"(?m)^(?P<hashes>#{1,4})\s+(?P<title>.+?)\s*$")

#: Secciones que responden a cada hueco del onboarding.
PREREQUISITE_HINTS = (
    "requisito", "prerrequisito", "requerimiento", "requiere", "dependencia", "instal",
    "requirement", "prerequisite", "install",
)
#: Títulos que no son instrucciones de arranque aunque mencionen comandos.
NOT_SETUP = ("cobertura", "coverage", "tests", "pruebas", "reporte")
SETUP_HINTS = (
    "puesta en marcha", "empezar", "comenzar", "arranque", "arrancar", "inicio rápido",
    "quickstart", "quick start", "getting started", "ejecutar", "ejecución", "ejecuta",
    "levantar", "poner en marcha", "dev server", "run",
)
PURPOSE_HINTS = (
    "qué es", "que es", "descripción", "descripcion", "introducción", "introduccion",
    "about", "overview", "propósito", "proposito",
)


@dataclass(frozen=True, slots=True)
class DocSection:
    """Una sección de la documentación existente, con su rango de líneas."""

    path: str
    title: str
    body: str
    line_start: int
    line_end: int

    @property
    def citation(self) -> str:
        return f"{self.path}#L{self.line_start}-L{self.line_end}"

    def matches(self, hints: Sequence[str]) -> bool:
        haystack = f"{self.title} {self.body[:200]}".lower()
        return any(hint in haystack for hint in hints)

    def to_fact(self) -> Fact:
        return Fact(
            kind="doc_section",
            subject=f"{self.path} › {self.title}",
            detail=self.body[:MAX_TEXT] or "—",
            citation=self.citation,
            attributes={"source": self.path, "title": self.title},
        )


def parse_sections(path: str, source: str) -> list[DocSection]:
    """Secciones de nivel 1–3 con su primer párrafo como cuerpo."""
    headings = list(_HEADING_RE.finditer(source))
    sections: list[DocSection] = []
    for index, match in enumerate(headings):
        level = len(match.group("hashes"))
        if level > 3:
            continue
        title = match.group("title").strip().strip("#").strip()
        if not title:
            continue
        start = match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(source)
        body = _first_paragraph(source[start:end])
        line_start = source.count("\n", 0, match.start()) + 1
        line_end = source.count("\n", 0, end) + 1
        sections.append(DocSection(path, title, body, line_start, line_end))
        if len(sections) >= MAX_SECTIONS:
            break
    return sections


def _first_paragraph(text: str) -> str:
    """Primer bloque con contenido real: ni tablas ni imágenes ni insignias."""
    for block in re.split(r"\n\s*\n", text):
        cleaned = " ".join(
            line.strip() for line in block.splitlines() if not line.strip().startswith(("|", "![", "[![", "```", "<"))
        )
        cleaned = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", cleaned).strip()
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cleaned).strip()
        # Un párrafo corto también es evidencia: el umbral alto descartaba introducciones reales.
        if len(cleaned) >= 20 and len(cleaned.split()) >= 3:
            return cleaned[:MAX_TEXT]
    return ""


def discover(root: Path | str, files: Mapping[str, Path] | None = None) -> list[DocSection]:
    """Secciones de la documentación existente del proyecto, sin entrar en `docs/generated`."""
    root_path = Path(root)
    candidates: list[Path] = []
    for name in DOC_FILES:
        candidate = root_path / name
        if candidate.is_file():
            candidates.append(candidate)
    for directory in DOC_DIRS:
        base = root_path / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            if "generated" in path.parts or "node_modules" in path.parts:
                continue
            candidates.append(path)

    sections: list[DocSection] = []
    for path in dict.fromkeys(candidates):
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(root_path).as_posix()
        sections.extend(parse_sections(rel, source))
        if len(sections) >= MAX_SECTIONS:
            break
    return sections[:MAX_SECTIONS]


def find(sections: Sequence[DocSection], hints: Sequence[str], limit: int = 3) -> list[DocSection]:
    """Secciones que responden a un hueco concreto, con el título por delante del cuerpo.

    Prioriza las secciones cuyo **título** coincide («Prerrequisitos» gana a un párrafo de cobertura
    que menciona `npm run`): sin esto, el onboarding citaba el reporte de cobertura como si fuera la
    puesta en marcha.
    """
    scored: list[tuple[int, DocSection]] = []
    for position, section in enumerate(sections):
        title = section.title.lower()
        if any(word in title for word in NOT_SETUP):
            continue  # un reporte de cobertura no es la puesta en marcha
        # Coincidencia por **título**: buscar en el cuerpo traía secciones que sólo mencionaban el
        # comando de pasada (un apartado de documentación que hablaba de «modos de ejecución»).
        if any(hint in title for hint in hints):
            scored.append((position, section))
    return [section for _position, section in scored[:limit]]


__all__ = [
    "DOC_DIRS",
    "DOC_FILES",
    "DocSection",
    "MAX_SECTIONS",
    "PREREQUISITE_HINTS",
    "PURPOSE_HINTS",
    "SETUP_HINTS",
    "discover",
    "find",
    "parse_sections",
]
