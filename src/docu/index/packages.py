"""Detección de paquetes: la unidad arquitectónica que faltaba.

Un módulo Maven y un paquete Python son la misma cosa conceptual —una unidad de despliegue y de
dependencia interna— y el producto los trataba distinto: solo el primero existía. Aquí se detectan
ambos con evidencia citable, sin inventar jerarquías que el código no declara.

Regla de evidencia: un paquete se cita por el archivo que lo **declara** (`__init__.py` en Python,
la sentencia `package` en Java). Si no hay declaración, no hay hecho.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

JAVA_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class DetectedPackage:
    """Unidad arquitectónica detectada, con el archivo que la declara."""

    name: str
    language: str
    files: tuple[str, ...]
    declaration: str  # ruta#L inicio-L fin de la declaración

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def citation(self) -> str:
        return self.declaration


def _python_packages(files: Mapping[str, Path]) -> list[DetectedPackage]:
    """Un paquete Python se reconoce por `__init__.py`; el nombre es su ruta sin el prefijo `src/`."""
    python_files = [rel for rel in files if rel.endswith(".py")]
    markers = [
        rel for rel in python_files if rel.rsplit("/", 1)[-1] == "__init__.py"
    ]
    packages: list[DetectedPackage] = []
    for marker in sorted(markers):
        package_dir = marker.rsplit("/", 1)[0] if "/" in marker else "."
        prefix = "src/" if package_dir.startswith("src/") else ""
        name = package_dir[len(prefix) :].replace("/", ".") if package_dir != "." else "."
        # Miembros **directos**: el paquete no absorbe sus subpaquetes. Si se cuenta recursivo,
        # `docu` reclama 45 archivos y su diagrama de clases mezcla capas que no le pertenecen.
        members = tuple(
            sorted(
                rel
                for rel in python_files
                if (rel.rsplit("/", 1)[0] if "/" in rel else ".") == package_dir
            )
        )
        line_count = _line_count(Path(files[marker]))
        packages.append(
            DetectedPackage(
                name=name,
                language="python",
                files=members,
                declaration=f"{marker}#L1-L{max(1, line_count)}",
            )
        )
    return packages


def _java_packages(files: Mapping[str, Path]) -> list[DetectedPackage]:
    """En Java el paquete se declara en cada archivo: se agrupa por nombre y se cita el primero."""
    grouped: dict[str, list[str]] = {}
    declarations: dict[str, str] = {}
    for rel in sorted(files):
        if not rel.endswith(".java"):
            continue
        text = _read(files[rel])
        match = JAVA_PACKAGE_RE.search(text)
        if match is None:
            continue
        name = match.group(1)
        line = text[: match.start()].count("\n") + 1
        grouped.setdefault(name, []).append(rel)
        declarations.setdefault(name, f"{rel}#L{line}-L{line}")
    return [
        DetectedPackage(
            name=name,
            language="java",
            files=tuple(sorted(members)),
            declaration=declarations[name],
        )
        for name, members in sorted(grouped.items())
    ]


def _typescript_packages(files: Mapping[str, Path]) -> list[DetectedPackage]:
    """Unidades de TypeScript/JavaScript.

    Dos convenciones, porque el ecosistema no tiene una sola:
    - **barril**: directorio con `index.ts`/`index.tsx` (lo que declara el paquete);
    - **directorio**: carpeta con al menos 3 archivos de código y sin barril (React, Express y
      proyectos Vite agrupan por carpeta: `components`, `hooks`, `api`). Sin esto, un proyecto
      React aparece con «paquetes: 0» y su arquitectura se pierde.
    """
    code_files = {
        rel: path
        for rel, path in files.items()
        if rel.endswith((".ts", ".tsx", ".js", ".jsx"))
    }
    packages: list[DetectedPackage] = []
    barrel_dirs: set[str] = set()
    for rel in sorted(code_files):
        if not rel.endswith(("/index.ts", "/index.tsx")):
            continue
        package_dir = rel.rsplit("/", 1)[0]
        barrel_dirs.add(package_dir)
        members = tuple(
            sorted(
                item
                for item in code_files
                if (item.rsplit("/", 1)[0] if "/" in item else ".") == package_dir
            )
        )
        line_count = _line_count(Path(code_files[rel]))
        packages.append(
            DetectedPackage(
                name=package_dir.replace("/", "."),
                language="typescript",
                files=members,
                declaration=f"{rel}#L1-L{max(1, line_count)}",
            )
        )

    grouped: dict[str, list[str]] = {}
    for rel in sorted(code_files):
        directory = rel.rsplit("/", 1)[0] if "/" in rel else "."
        if directory in barrel_dirs:
            continue
        grouped.setdefault(directory, []).append(rel)

    for directory, members in sorted(grouped.items()):
        if len(members) < 3 or directory == ".":
            continue
        # Unidades por carpeta sólo en profundidad razonable: `vendor/includes/assets/js` no es una
        # unidad de arquitectura aunque tenga tres archivos.
        if directory.count("/") + 1 > MAX_DIRECTORY_DEPTH:
            continue
        first = members[0]
        packages.append(
            DetectedPackage(
                name=directory.replace("/", "."),
                # Se marca el origen: no hay archivo que declare esta unidad, y la cita apunta al
                # primer archivo completo. Decirlo evita que la cita parezca más fuerte de lo que es.
                language="typescript (directorio)",
                files=tuple(members),
                declaration=f"{first}#L1-L{max(1, _line_count(Path(files[first])))}",
            )
        )
    return packages


def detect_packages(files: Mapping[str, Path]) -> tuple[DetectedPackage, ...]:
    """Todos los paquetes detectables, sin duplicar lenguajes ni inventar contenedores."""
    found = [*_python_packages(files), *_java_packages(files), *_typescript_packages(files)]
    return tuple(sorted(found, key=lambda item: (item.language, item.name)))


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


MAX_DIRECTORY_DEPTH = 3


def _line_count(path: Path) -> int:
    """Lineas reales del archivo.

    `text.count("\\n") + 1` cuenta una linea fantasma cuando el archivo termina en salto de linea,
    y eso produce citas `L1-L11` sobre archivos de 10 lineas: un fallo de precisión que invalida la
    promesa de trazabilidad.
    """
    return max(1, len(_read(path).splitlines()))


def top_level(packages: Sequence[DetectedPackage]) -> tuple[str, ...]:
    """Raíces de primer nivel: lo que un lector necesita para orientarse en el proyecto."""
    roots: list[str] = []
    for package in packages:
        head = package.name.split(".")[0]
        if head and head not in roots:
            roots.append(head)
    return tuple(sorted(roots))


__all__ = ["DetectedPackage", "detect_packages", "top_level"]
