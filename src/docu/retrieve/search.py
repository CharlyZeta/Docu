"""Busqueda lexica sobre documentos generados.

Este modulo es lo que consume el servidor MCP: un agente de codigo pregunta en lenguaje natural y
recibe secciones del documento con su cita. Se implementa BM25 aqui (y no se importa del arnes de
evaluacion) porque el producto no debe depender de su propio banco de pruebas.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from docu.retrieve.glossary import expand, fold

_WORD = re.compile(r"[\w.\-]+", re.UNICODE)
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_STOP = frozenset(
    "de la el los las en y que con para por un una del al se como es son su sus lo le the a of and "
    "or in to is are for with on by".split()
)


def tokenize(text: str) -> list[str]:
    """Tokens con plegado de acentos y descomposicion de CamelCase."""
    tokens: list[str] = []
    for raw in _WORD.findall(fold(text)):
        for part in re.split(r"[_.\-]", raw):
            if not part:
                continue
            lowered = part.lower()
            if lowered not in _STOP:
                tokens.append(lowered)
            for match in _CAMEL.finditer(part):
                sub = match.group(0).lower()
                if len(sub) > 2 and sub not in _STOP:
                    tokens.append(sub)
    return tokens


def looks_like_identifier(query: str) -> bool:
    """¿La consulta es código tecleado o una pregunta humana?

    Criterio estricto: una palabra capitalizada NO es un identificador —«Spring Boot» y «CORS»
    aparecen en preguntas humanas y enrutarlas al canal estructural cuesta 0.12 de MRR (medido en
    `eval/README.md`, F-12)—. Se exige forma de código: punto entre palabras, guion bajo, kebab o
    camelCase real.
    """
    for token in query.split():
        cleaned = token.strip('`"\'(),:;¿?¿!¡[]{}')
        if re.search(r"\w\.\w", cleaned):
            return True
        if "_" in cleaned:
            return True
        if re.search(r"\w-\w", cleaned):
            return True
        if re.search(r"[a-z][A-Z]", cleaned):
            return True
    return False


@dataclass(frozen=True, slots=True)
class Section:
    """Seccion de un documento: la unidad que se devuelve a un agente."""

    document: str
    heading: str
    body: str
    level: str = ""
    tokens: tuple[str, ...] = ()
    citations: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return f"{self.heading}\n{self.body}"

    def to_dict(self) -> dict[str, object]:
        return {
            "document": self.document,
            "level": self.level,
            "heading": self.heading,
            "body": self.body,
            "citations": list(self.citations),
        }


def split_sections(path: Path, content: str, level: str = "") -> list[Section]:
    """Divide un Markdown por encabezados de nivel 2 conservando las citas de cada bloque."""
    sections: list[Section] = []
    heading = "(inicio)"
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if not body and heading == "(inicio)":
            return
        citations = tuple(dict.fromkeys(re.findall(r"`([^`]+#L\d+(?:-L\d+)?)`", body)))
        sections.append(
            Section(
                document=path.name,
                heading=heading,
                body=body,
                level=level,
                tokens=tuple(tokenize(f"{heading} {body}")),
                citations=citations,
            )
        )

    for line in content.splitlines():
        if line.startswith("## "):
            flush()
            heading = line[3:].strip()
            buffer = []
            continue
        buffer.append(line)
    flush()
    return [section for section in sections if section.body or section.heading != "(inicio)"]


@dataclass
class DocIndex:
    """Indice BM25 en memoria sobre las secciones de los documentos generados."""

    sections: list[Section] = field(default_factory=list)
    k1: float = 1.5
    b: float = 0.75
    glossary: Mapping[str, Sequence[str]] | None = None
    _df: dict[str, int] = field(default_factory=dict, init=False)
    _avgdl: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        lengths = [len(section.tokens) for section in self.sections]
        for section in self.sections:
            for term in set(section.tokens):
                self._df[term] = self._df.get(term, 0) + 1
        self._avgdl = (sum(lengths) / len(lengths)) if lengths else 0.0

    @classmethod
    def from_directory(cls, directory: Path | str, glossary: Mapping[str, Sequence[str]] | None = None) -> "DocIndex":
        """Carga todos los `.md` de un directorio de documentacion generada."""
        sections: list[Section] = []
        root = Path(directory)
        if root.exists():
            for path in sorted(root.glob("*.md")):
                level = path.name.split("-", 1)[0]
                sections.extend(split_sections(path, path.read_text(encoding="utf-8"), level))
        return cls(sections=sections, glossary=glossary)

    def _idf(self, term: str) -> float:
        total = len(self.sections)
        df = self._df.get(term, 0)
        return math.log(1 + (total - df + 0.5) / (df + 0.5))

    def search(
        self,
        query: str,
        limit: int = 5,
        expand_query: bool = True,
        level: str | None = None,
    ) -> list[tuple[Section, float]]:
        """Devuelve las secciones mas relevantes. `expand_query` aplica el glosario de dominio."""
        if not self.sections:
            return []
        text = expand(query, self.glossary) if expand_query else query
        terms = set(tokenize(text))
        scored: list[tuple[Section, float]] = []
        for section in self.sections:
            if level and section.level and section.level != level:
                continue
            length = len(section.tokens)
            score = 0.0
            counts: dict[str, int] = {}
            for token in section.tokens:
                if token in terms:
                    counts[token] = counts.get(token, 0) + 1
            for term, frequency in counts.items():
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * (length / self._avgdl if self._avgdl else 1.0)
                )
                score += self._idf(term) * (frequency * (self.k1 + 1)) / denominator
            if score > 0:
                scored.append((section, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    @property
    def is_empty(self) -> bool:
        return not self.sections

    def headings(self) -> Iterable[str]:
        return (section.heading for section in self.sections)
