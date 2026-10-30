"""Lectura de `.gitignore`: si el proyecto dice que algo no es fuente, no es fuente.

`docu` tenía su propia lista de exclusiones y **no miraba el `.gitignore`**, así que indexaba
`coverage/`, artefactos de reportes y mirrors de cliente. El `.gitignore` es la declaración más
autorizada de qué es ruido en un repositorio: se respeta, con la misma semántica que git en los casos
que importan (negación, directorios, anclaje y `**`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    raw: str
    pattern: str
    negate: bool
    directory_only: bool
    anchored: bool
    regex: re.Pattern[str]


def _translate(pattern: str) -> re.Pattern[str]:
    """Glob de git → regex. Se soportan `**`, `*`, `?` y clases simples."""
    out: list[str] = []
    index = 0
    size = len(pattern)
    while index < size:
        char = pattern[index]
        if char == "*":
            if pattern.startswith("**", index):
                # `**/` abarca cero o más directorios; `**` suelto abarca cualquier cosa.
                if pattern.startswith("**/", index):
                    out.append("(?:[^/]+/)*")
                    index += 3
                    continue
                out.append(".*")
                index += 2
                continue
            out.append("[^/]*")
            index += 1
            continue
        if char == "?":
            out.append("[^/]")
            index += 1
            continue
        if char == "[":
            closing = pattern.find("]", index)
            if closing != -1:
                out.append(pattern[index : closing + 1])
                index = closing + 1
                continue
        out.append(re.escape(char))
        index += 1
    return re.compile("^" + "".join(out) + "$")


def parse(text: str) -> list[IgnoreRule]:
    """Reglas del archivo. Ignora comentarios y líneas vacías, como git."""
    rules: list[IgnoreRule] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        negate = stripped.startswith("!")
        if negate:
            stripped = stripped[1:]
        directory_only = stripped.endswith("/")
        stripped = stripped.rstrip("/")
        if not stripped:
            continue
        anchored = stripped.startswith("/") or "/" in stripped.rstrip("/")
        stripped = stripped.lstrip("/")
        rules.append(
            IgnoreRule(
                raw=line.rstrip(),
                pattern=stripped,
                negate=negate,
                directory_only=directory_only,
                anchored=anchored,
                regex=_translate(stripped),
            )
        )
    return rules


def load(root: Path | str) -> list[IgnoreRule]:
    """Reglas del `.gitignore` de la raíz, si existe."""
    path = Path(root) / ".gitignore"
    try:
        return parse(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []


def is_ignored(rel: str, rules: Sequence[IgnoreRule], is_dir: bool = False) -> bool:
    """Última regla que aplica gana; `!patrón` vuelve a incluir.

    Candidatos: la ruta completa y cada directorio contenedor (para los patrones anclados o con `/`),
    más el nombre de cada componente (para los patrones sueltos como `coverage`, que en git ignoran
    cualquier directorio con ese nombre a cualquier profundidad).
    """
    if not rules:
        return False
    rel = rel.replace("\\", "/").lstrip("./")
    parts = rel.split("/")
    prefixes = ["/".join(parts[: index + 1]) for index in range(len(parts) - 1)]
    names = [parts[-1], *(prefix.rsplit("/", 1)[-1] for prefix in prefixes)]
    full_candidates = [rel, *prefixes]
    ignored = False
    for rule in rules:
        candidates = full_candidates if rule.anchored else [*full_candidates, *names]
        if rule.directory_only:
            # Patrón de directorio: no aplica al archivo en sí, sólo a sus contenedores.
            candidates = [item for item in candidates if item != rel]
            if is_dir:
                candidates = [rel, *candidates]
            if not candidates:
                continue
        if any(rule.regex.match(candidate) for candidate in candidates):
            ignored = not rule.negate
    return ignored


def _prefixes(rel: str) -> list[str]:
    """Rutas de los directorios contenedores, de la más cercana a la raíz."""
    parts = rel.split("/")[:-1]
    return ["/".join(parts[: index + 1]) for index in range(len(parts))]


__all__ = ["IgnoreRule", "is_ignored", "load", "parse"]
