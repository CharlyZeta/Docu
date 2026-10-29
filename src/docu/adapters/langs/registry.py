"""Registro de adaptadores por extension: el nucleo no conoce lenguajes concretos."""

from __future__ import annotations

from docu.adapters.langs.java import JavaLangAdapter
from docu.adapters.langs.python import PythonLangAdapter
from docu.adapters.langs.typescript import TypeScriptLangAdapter

ADAPTERS: tuple[object, ...] = (JavaLangAdapter(), PythonLangAdapter(), TypeScriptLangAdapter())

SOURCE_SUFFIXES: tuple[str, ...] = tuple(
    sorted({glob.lstrip("*") for adapter in ADAPTERS for glob in adapter.file_globs})  # type: ignore[attr-defined]
)


def adapter_for(path: str) -> object | None:
    """Adaptador cuyo glob casa con la ruta, o `None` si el lenguaje no esta soportado."""
    for adapter in ADAPTERS:
        for glob in adapter.file_globs:  # type: ignore[attr-defined]
            if path.endswith(glob.lstrip("*")):
                return adapter
    return None


def supported_languages() -> tuple[str, ...]:
    return tuple(adapter.language for adapter in ADAPTERS)  # type: ignore[attr-defined]
