"""Snapshots web persistidos: la documentación cita el texto congelado, no la página viva."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from docu.adapters.sources.web import Snapshot, WebError, capture
from docu.generate.facts import Fact

INDEX_NAME = "web.json"
SNAPSHOT_DIR = "web"


@dataclass(frozen=True, slots=True)
class WebDocument:
    url: str
    rel: str
    sha: str
    captured_at: str
    lines: int
    chars: int
    usable: bool
    error: str = ""

    @property
    def citation(self) -> str:
        return f"{self.rel}#L1-L{max(1, self.lines)}"

    def to_fact(self) -> Fact:
        status = "texto congelado" if self.usable else f"no capturada: {self.error or 'sin texto'}"
        return Fact(
            kind="web_source",
            subject=self.url,
            detail=f"{status} · {self.lines} líneas · {self.chars} caract. · {self.sha[:12]} · {self.captured_at}",
            citation=self.citation,
            attributes={
                "sha": self.sha,
                "captured_at": self.captured_at,
                "lines": str(self.lines),
                "status": status,
            },
        )


def _index_path(root: Path) -> Path:
    return root / ".docu" / INDEX_NAME


def read_index(root: Path) -> dict[str, dict[str, object]]:
    path = _index_path(root)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_index(root: Path, entries: Mapping[str, Mapping[str, object]]) -> None:
    path = _index_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")


def capture_urls(
    root: Path | str,
    urls: Sequence[str],
    allowlist: Sequence[str],
    docs_dir: Path | str,
    opener=None,
) -> tuple[list[WebDocument], list[str]]:
    """Captura las URLs permitidas y escribe su texto en `<docs>/web/`.

    Los errores no detienen la corrida: se devuelven como documentos no usables con su motivo, porque
    una fuente externa caída no debe romper la documentación del repositorio.
    """
    root_path = Path(root)
    target = Path(docs_dir) / SNAPSHOT_DIR
    index = read_index(root_path)
    documents: list[WebDocument] = []
    errors: list[str] = []
    for url in urls:
        try:
            snapshot: Snapshot = capture(url, allowlist, opener=opener)
        except WebError as error:
            errors.append(str(error))
            existing = index.get(url) or {}
            rel = str(existing.get("rel", ""))
            if rel and (root_path / rel).is_file():
                documents.append(
                    WebDocument(
                        url=url,
                        rel=rel,
                        sha=str(existing.get("sha", "")),
                        captured_at=str(existing.get("captured_at", "")),
                        lines=int(existing.get("lines", 0) or 0),
                        chars=int(existing.get("chars", 0) or 0),
                        usable=True,
                        error=str(error),
                    )
                )
            else:
                documents.append(
                    WebDocument(url=url, rel="", sha="", captured_at="", lines=0, chars=0, usable=False, error=str(error))
                )
            continue
        target.mkdir(parents=True, exist_ok=True)
        rel = f"{SNAPSHOT_DIR}/{snapshot.slug}.txt"
        destination = Path(docs_dir) / rel
        destination.write_text(snapshot.text + "\n", encoding="utf-8")
        # La cita debe resolverse desde la raíz del proyecto: se guarda la ruta relativa a la raíz
        # cuando el snapshot vive dentro del repositorio.
        try:
            cite_rel = destination.resolve().relative_to(root_path.resolve()).as_posix()
        except ValueError:
            cite_rel = destination.as_posix()
        index[url] = {
            "rel": cite_rel,
            "sha": snapshot.sha,
            "captured_at": snapshot.captured_at,
            "lines": snapshot.lines,
            "chars": len(snapshot.text),
        }
        documents.append(
            WebDocument(
                url=url,
                rel=cite_rel,
                sha=snapshot.sha,
                captured_at=snapshot.captured_at,
                lines=snapshot.lines,
                chars=len(snapshot.text),
                usable=True,
            )
        )
    if documents:
        _write_index(root_path, index)
    return documents, errors


def load_documents(root: Path | str, urls: Iterable[str] = ()) -> list[WebDocument]:
    """Documentos ya congelados: **no toca la red**, así la generación es reproducible."""
    root_path = Path(root)
    index = read_index(root_path)
    wanted = list(urls) or list(index)
    documents: list[WebDocument] = []
    for url in wanted:
        entry = index.get(url)
        if not entry:
            documents.append(
                WebDocument(
                    url=url,
                    rel="",
                    sha="",
                    captured_at="",
                    lines=0,
                    chars=0,
                    usable=False,
                    error="sin snapshot: ejecuta `docu web --fetch`",
                )
            )
            continue
        rel = str(entry.get("rel", ""))
        path = root_path / rel
        lines = int(entry.get("lines", 0) or 0)
        documents.append(
            WebDocument(
                url=url,
                rel=rel,
                sha=str(entry.get("sha", "")),
                captured_at=str(entry.get("captured_at", "")),
                lines=lines,
                chars=int(entry.get("chars", 0) or 0),
                usable=path.is_file() and lines > 0,
                error="" if path.is_file() else "snapshot perdido en disco",
            )
        )
    return documents


def web_facts(documents: Sequence[WebDocument]) -> list[Fact]:
    return [document.to_fact() for document in documents if document.rel]


def check_stale(root: Path | str, allowlist: Sequence[str], opener=None) -> list[tuple[str, str]]:
    """Compara los snapshots con la web actual. Sólo lo llama `--check`: usa red a propósito."""
    root_path = Path(root)
    index = read_index(root_path)
    report: list[tuple[str, str]] = []
    for url, entry in index.items():
        try:
            snapshot = capture(url, allowlist, opener=opener)
        except WebError as error:
            report.append((url, f"error: {error}"))
            continue
        if snapshot.sha == str(entry.get("sha")):
            report.append((url, "vigente"))
        else:
            report.append((url, "cambió: hay que recapturar"))
    return report


__all__ = [
    "INDEX_NAME",
    "SNAPSHOT_DIR",
    "WebDocument",
    "capture_urls",
    "check_stale",
    "load_documents",
    "read_index",
    "web_facts",
]
