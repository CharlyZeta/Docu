"""Descubrimiento y reporte de PDFs como fuentes citables.

La unidad de cita es la **página** (`manual.pdf#p3`): un PDF no tiene líneas estables, y citar la
página es lo único que un lector puede abrir y comprobar. El texto extraído se guarda al lado de la
documentación para que sea legible sin herramientas.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from docu.adapters.sources.pdf import PdfText, extract, pages_text
from docu.core.contracts import sha256_of
from docu.generate.facts import Fact

#: Topes: un repositorio con cientos de PDFs no debe convertir la generación en una espera infinita.
MAX_PDF_FILES = 40
MAX_PDF_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PdfDocument:
    rel: str
    pages: int
    chars: int
    method: str
    status: str
    usable: bool
    warnings: tuple[str, ...] = ()

    @property
    def citation(self) -> str:
        return f"{self.rel}#p1"

    def to_fact(self) -> Fact:
        extra = f" · {'; '.join(self.warnings)}" if self.warnings else ""
        return Fact(
            kind="pdf_document",
            subject=self.rel,
            detail=f"{self.status} · {self.pages} pág. · {self.chars} caract. · {self.method}{extra}",
            citation=self.citation,
            attributes={
                "pages": str(self.pages),
                "chars": str(self.chars),
                "method": self.method,
                "status": self.status,
            },
        )


def discover_pdfs(
    root: Path | str,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    include_tests: bool = False,
    limit: int = MAX_PDF_FILES,
) -> list[str]:
    """PDFs del repositorio, respetando las mismas exclusiones que el resto de la ingesta."""
    from docu.generate.pipeline import (
        EXCLUDED_PARTS,
        _effective_exclude,
        _is_test_path,
        _path_matches,
    )
    from docu.index.ignore import is_ignored, load as load_ignore

    root_path = Path(root)
    patterns = _effective_exclude(exclude)
    rules = load_ignore(root_path)
    found: list[str] = []
    for candidate in sorted(root_path.rglob("*")):
        if not candidate.is_file() or candidate.suffix.lower() != ".pdf":
            continue
        rel = candidate.relative_to(root_path)
        rel_text = rel.as_posix()
        if any(part in EXCLUDED_PARTS for part in rel.parts):
            continue
        if is_ignored(rel_text, rules):
            continue
        if patterns and _path_matches(rel_text, patterns):
            continue
        if include and not _path_matches(rel_text, include):
            continue
        if not include_tests and _is_test_path(rel):
            continue
        if candidate.stat().st_size > MAX_PDF_BYTES:
            continue
        found.append(rel_text)
        if len(found) >= limit:
            break
    return found


def load_document(root: Path | str, rel: str, data: bytes | None = None) -> tuple[PdfDocument, str]:
    """Extrae un PDF y devuelve su reporte más el texto por páginas."""
    root_path = Path(root)
    payload = data if data is not None else (root_path / rel).read_bytes()
    result: PdfText = extract(payload)
    document = PdfDocument(
        rel=rel,
        pages=result.total_pages,
        chars=result.chars,
        method=result.method,
        status=result.status,
        usable=result.usable,
        warnings=result.warnings,
    )
    return document, pages_text(result)


def load_all(
    root: Path | str,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    include_tests: bool = False,
    limit: int = MAX_PDF_FILES,
) -> tuple[list[PdfDocument], dict[str, str], dict[str, str]]:
    """Documentos, texto por página y huellas para la frescura."""
    root_path = Path(root)
    documents: list[PdfDocument] = []
    texts: dict[str, str] = {}
    digests: dict[str, str] = {}
    for rel in discover_pdfs(root_path, include, exclude, include_tests, limit):
        try:
            payload = (root_path / rel).read_bytes()
        except OSError:
            continue
        digests[rel] = sha256_of(payload.hex())[:12]
        document, text = load_document(root_path, rel, payload)
        documents.append(document)
        if text:
            texts[rel] = text
    return documents, texts, digests


def pdf_facts(documents: Sequence[PdfDocument]) -> list[Fact]:
    return [document.to_fact() for document in documents]


def write_sidecars(texts: Mapping[str, str], directory: Path) -> list[Path]:
    """Escribe el texto extraído junto a la documentación: legible sin herramientas."""
    written: list[Path] = []
    if not texts:
        return written
    directory.mkdir(parents=True, exist_ok=True)
    for rel, text in sorted(texts.items()):
        name = rel.replace("/", "__").removesuffix(".pdf") + ".txt"
        target = directory / name
        target.write_text(f"# {rel}\n\n{text}\n", encoding="utf-8")
        written.append(target)
    return written


__all__ = [
    "MAX_PDF_BYTES",
    "MAX_PDF_FILES",
    "PdfDocument",
    "discover_pdfs",
    "load_all",
    "load_document",
    "pdf_facts",
    "write_sidecars",
]
