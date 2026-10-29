"""Detección de stack y propuesta de perfil para `docu init`.

Vive en la **capa de entrega** a propósito: necesita adaptadores de lenguaje, el recolector de
hechos y el glosario. Antes estaba en `core/profile.py` con imports perezosos y eso rompía el
invariante del producto —`core` no debe depender de `adapters`—; el diagrama de arquitectura de este
mismo repositorio lo dejó a la vista.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from docu.adapters.langs.registry import adapter_for
from docu.core.profile import DEFAULT_EXCLUDE, LEVELS, Profile
from docu.generate.facts import symbol_facts
from docu.generate.pipeline import _discover, collect_facts, _read
from docu.retrieve.glossary import DEFAULT_GLOSSARY

#: Nombres de framework que, si aparecen en las dependencias, cambian el perfil propuesto.
FRAMEWORKS = ("spring-boot", "fastapi", "flask", "django", "nestjs", "express", "fastify")


def detect(root: Path) -> dict[str, object]:
    """Inspecciona el proyecto para proponer un perfil: lenguajes, frameworks y rutas."""
    root = Path(root)
    languages: set[str] = set()
    route_count = 0
    facts_all = []
    discovered = _discover(root)
    for rel, path in discovered.items():
        adapter = adapter_for(rel)
        if adapter is None:
            continue
        languages.add(str(adapter.language))  # type: ignore[attr-defined]
        source = _read(path)
        facts = symbol_facts(adapter.symbols(rel, source))  # type: ignore[attr-defined]
        facts_all.extend(facts)
        route_count += sum(1 for fact in facts if fact.kind == "route")

    facts, _sources = collect_facts(root)
    dependencies = [fact.subject.lower() for fact in facts if fact.kind == "dependency"]
    frameworks = sorted(
        {name for name in FRAMEWORKS if any(name in dependency for dependency in dependencies)}
    )
    return {
        "languages": sorted(languages),
        "frameworks": frameworks,
        "routes": route_count,
        "files": len(discovered),
        "facts": len(facts),
    }


def propose(root: Path, *, project: str | None = None) -> Profile:
    """Perfil sugerido a partir de lo detectado, listo para que un humano lo corrija."""
    root = Path(root)
    detection = detect(root)
    languages: Sequence[str] = detection["languages"]  # type: ignore[assignment]
    frameworks: Sequence[str] = detection["frameworks"]  # type: ignore[assignment]
    routes: int = detection["routes"]  # type: ignore[assignment]

    levels = ["l1", "l4"]
    if routes > 0:
        levels.append("l3")

    # El glosario se siembra solo cuando hay evidencia de que aplica: inventar vocabulario de un
    # dominio desconocido seria peor que no sembrarlo.
    glossary: dict[str, tuple[str, ...]] = {}
    if "spring-boot" in frameworks:
        glossary = dict(DEFAULT_GLOSSARY)

    # No se propone `include`: restringir la ingesta por convencion (`src/**`) deja fuera
    # proyectos con otra estructura y produce un documento vacio que parece un fallo del agente.
    return Profile(
        project=project or root.name,
        levels=tuple(level for level in LEVELS if level in levels),
        exclude=DEFAULT_EXCLUDE,
        glossary=glossary,
        raw={},
    )


__all__ = ["FRAMEWORKS", "detect", "propose"]
