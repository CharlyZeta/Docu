"""Perfil del proyecto: el contrato de entrada del producto.

Hasta ahora el perfil existía como archivo pero solo alimentaba el hash de frescura. Aquí se define
su esquema, su validación y su lectura, para que la primera instalación sea **revisar una propuesta**
en lugar de escribir configuración desde cero.

Regla: los valores ausentes tienen default documentado; los valores inválidos fallan ruidosamente,
porque un perfil mal escrito produce documentación que parece correcta y no lo es.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping, Sequence

from docu.core.contracts import Mode
from docu.core.policy import Thresholds
from docu.core.yamlmini import YamlError, parse

LEVELS = ("l1", "l2", "l3", "l4")
SUPPORTED_LEVELS = ("l1", "l3", "l4")  # l2 aun no implementado

DEFAULT_EXCLUDE = (
    "*/target/*",
    "target/*",
    "*/build/*",
    "build/*",
    "dist/*",
    "out/*",
    "coverage/*",
    "__pycache__/*",
    "*/.pytest_cache/*",
    "*/node_modules/*",
    "node_modules/*",
    "*/.git/*",
    ".git/*",
    ".sdd/*",
    ".agents/*",
    ".venv/*",
    "venv/*",
    "docs/generated/*",
)


class ProfileError(ValueError):
    """El perfil no cumple el esquema: mejor fallar que documentar con supuestos equivocados."""


@dataclass(frozen=True, slots=True)
class Profile:
    """Configuración efectiva de una instalación."""

    project: str
    mode: Mode = Mode.APPLY
    levels: tuple[str, ...] = ("l1", "l4")
    output_dir: str = "docs/generated"
    language: str = "es"
    ttl_days: int = 90
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE
    thresholds: Thresholds = field(default_factory=Thresholds)
    glossary: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    promotion_delta: float = 0.05
    rollback_drop: float = 0.05
    federate: bool = False
    path: Path | None = None
    raw: Mapping[str, object] = field(default_factory=dict)

    @property
    def exists(self) -> bool:
        return self.path is not None and self.path.exists()

    @property
    def effective_exclude(self) -> tuple[str, ...]:
        """Exclusiones aplicadas = las del archivo + los defaults de higiene.

        Se calculan al usar el perfil, no al cargarlo: si se fusionaran en la carga, el archivo
        dejaría de reflejar el comportamiento y la orden de cambio nunca podría proponer nada.
        """
        return tuple(dict.fromkeys((*self.exclude, *DEFAULT_EXCLUDE)))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "project": self.project,
            "mode": self.mode.value,
            "output": {"dir": self.output_dir, "levels": {level: level in self.levels for level in LEVELS}, "language": self.language},
            "freshness": {"ttl_days": self.ttl_days},
            "sources": {"git": {"include": list(self.include), "exclude": list(self.exclude)}},
            "acceptance": {
                "thresholds": {
                    "accuracy": self.thresholds.accuracy,
                    "completeness": self.thresholds.completeness,
                    "attribution": self.thresholds.attribution,
                    "conciseness": self.thresholds.conciseness,
                }
            },
            "learn": {
                "promotion_delta": self.promotion_delta,
                "rollback_drop": self.rollback_drop,
                "federate": self.federate,
            },
            "glossary": {phrase: list(terms) for phrase, terms in self.glossary.items()},
        }


# --------------------------------------------------------------------------- carga


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProfileError(f"'{name}' debe ser un mapa")
    return value


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProfileError(f"'{name}' debe ser texto o lista de textos")
    return tuple(value)


def _levels(value: object) -> tuple[str, ...]:
    enabled = _mapping(value, "output.levels")
    chosen = tuple(level for level in LEVELS if bool(enabled.get(level, level in ("l1", "l4"))))
    unknown = tuple(level for level in chosen if level not in LEVELS)
    if unknown:
        raise ProfileError(f"niveles desconocidos: {', '.join(unknown)}")
    if not chosen:
        raise ProfileError("el perfil no habilita ningún nivel")
    return chosen


def _thresholds(value: object, defaults: Thresholds) -> Thresholds:
    acceptance = _mapping(value, "acceptance")
    block = _mapping(acceptance.get("thresholds"), "acceptance.thresholds")

    def number(key: str, fallback: float) -> float:
        raw = block.get(key, fallback)
        try:
            parsed = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ProfileError(f"umbral '{key}' debe ser numérico") from None
        if not 0 < parsed <= 10:
            raise ProfileError(f"umbral '{key}' fuera de rango (1..10): {parsed}")
        return parsed

    return Thresholds(
        accuracy=number("accuracy", defaults.accuracy),
        completeness=number("completeness", defaults.completeness),
        attribution=number("attribution", defaults.attribution),
        conciseness=number("conciseness", defaults.conciseness),
    )


def _glossary(value: object) -> dict[str, tuple[str, ...]]:
    block = _mapping(value, "glossary")
    glossary: dict[str, tuple[str, ...]] = {}
    for phrase, terms in block.items():
        glossary[str(phrase)] = _string_tuple(terms, f"glossary.{phrase}")
    return glossary


def from_dict(payload: Mapping[str, object], *, path: Path | None = None, fallback_project: str = "proyecto") -> Profile:
    """Construye el perfil efectivo, con defaults para lo ausente."""
    output = _mapping(payload.get("output"), "output")
    git = _mapping(_mapping(payload.get("sources"), "sources").get("git"), "sources.git")
    freshness = _mapping(payload.get("freshness"), "freshness")
    learn = _mapping(payload.get("learn"), "learn")

    mode_raw = str(payload.get("mode", "apply"))
    try:
        mode = Mode(mode_raw)
    except ValueError:
        raise ProfileError(f"modo desconocido: {mode_raw!r} (usa propose, apply o publish)") from None

    raw_ttl = freshness.get("ttl_days")
    if raw_ttl is None:
        ttl = 90
    else:
        try:
            ttl = int(raw_ttl)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ProfileError(f"freshness.ttl_days debe ser entero, no {raw_ttl!r}") from None
        if ttl <= 0:
            raise ProfileError("freshness.ttl_days debe ser positivo")

    exclude = _string_tuple(git.get("exclude"), "sources.git.exclude")

    return Profile(
        project=str(payload.get("project") or fallback_project),
        mode=mode,
        levels=_levels(output.get("levels")),
        output_dir=str(output.get("dir") or "docs/generated"),
        language=str(output.get("language") or "es"),
        ttl_days=ttl,
        include=_string_tuple(git.get("include"), "sources.git.include"),
        exclude=exclude,
        thresholds=_thresholds(payload.get("acceptance"), Thresholds()),
        glossary=_glossary(payload.get("glossary")),
        promotion_delta=float(learn.get("promotion_delta", 0.05) or 0.05),  # type: ignore[arg-type]
        rollback_drop=float(learn.get("rollback_drop", 0.05) or 0.05),  # type: ignore[arg-type]
        federate=bool(learn.get("federate", False)),
        path=path,
        raw=payload,
    )


def load(path: Path | str | None, *, fallback_project: str = "proyecto") -> Profile | None:
    """Carga el perfil si existe. Devuelve `None` si no hay archivo (no es un error)."""
    if path is None:
        return None
    target = Path(path)
    if not target.exists():
        return None
    try:
        payload = parse(target.read_text(encoding="utf-8"))
    except YamlError as error:
        raise ProfileError(f"perfil ilegible ({target}): {error}") from None
    return from_dict(payload, path=target, fallback_project=fallback_project)


def candidate_paths(root: Path) -> tuple[Path, ...]:
    return (root / "docu.profile.yaml", root / "docu.profile.yml", root / "docu.profile.json")


def find(root: Path) -> Path | None:
    """Primer perfil existente en la raíz, o `None`."""
    return next((path for path in candidate_paths(root) if path.exists()), None)


# --------------------------------------------------------------------------- propuesta


def detect(root: Path) -> dict[str, object]:
    """Inspecciona el proyecto para proponer un perfil: lenguajes, frameworks y rutas."""
    from docu.adapters.langs.registry import adapter_for
    from docu.generate.facts import symbol_facts
    from docu.generate.pipeline import EXCLUDED_PARTS, _discover, _read

    languages: set[str] = set()
    route_count = 0
    dependencies: list[str] = []
    facts_all = []
    for rel, path in _discover(root).items():
        adapter = adapter_for(rel)
        if adapter is None:
            continue
        languages.add(str(adapter.language))  # type: ignore[attr-defined]
        source = _read(path)
        facts = symbol_facts(adapter.symbols(rel, source))  # type: ignore[attr-defined]
        facts_all.extend(facts)
        route_count += sum(1 for fact in facts if fact.kind == "route")

    from docu.generate.pipeline import collect_facts

    facts, _sources = collect_facts(root)
    dependencies = [fact.subject.lower() for fact in facts if fact.kind == "dependency"]
    frameworks = sorted(
        {
            name
            for name in ("spring-boot", "fastapi", "flask", "django", "nestjs", "express", "fastify")
            if any(name in dependency for dependency in dependencies)
        }
    )
    _ = EXCLUDED_PARTS
    return {
        "languages": sorted(languages),
        "frameworks": frameworks,
        "routes": route_count,
        "files": len(_discover(root)),
        "facts": len(facts),
    }


def propose(root: Path, *, project: str | None = None) -> Profile:
    """Perfil sugerido a partir de lo detectado, listo para que un humano lo corrija."""
    from docu.retrieve.glossary import DEFAULT_GLOSSARY

    detection = detect(root)
    languages: Sequence[str] = detection["languages"]  # type: ignore[assignment]
    frameworks: Sequence[str] = detection["frameworks"]  # type: ignore[assignment]
    routes: int = detection["routes"]  # type: ignore[assignment]

    levels = ["l1", "l4"]
    if routes > 0:
        levels.append("l3")
    if "module" in detection:
        pass

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


def to_yaml(profile: Profile) -> str:
    """Serializa el perfil con comentarios: lo que se genera se entiende sin leer el código."""
    lines = [
        "# Perfil de aceptación de docu. Editarlo es decidir: la generación lo obedece.",
        "# Generado por `docu init`; revisa exclusiones, niveles y umbrales antes de confiar en él.",
        'schema_version: "1.0"',
        "",
        f"project: {profile.project}",
        f"mode: {profile.mode.value}                 # propose | apply | publish",
        "",
        "sources:",
        "  git:",
        "    ref: HEAD",
    ]
    if profile.include:
        lines.append("    include: [" + ", ".join(f'"{item}"' for item in profile.include) + "]")
    else:
        # Sin `include`, la ingesta cubre todo lo detectable. Escribir `["**/*"]` seria un
        # patrón que no casa con los archivos de la raíz y perdería el propio perfil y el POM.
        lines.append("    # include: []   # por defecto: todo lo detectable")
    lines.append("    exclude:")
    for pattern in profile.exclude:
        lines.append(f'      - "{pattern}"')
    lines.append("  pdf: []")
    lines.append("  web:")
    lines.append('    allowlist: ["docs.spring.io", "docs.python.org", "developer.mozilla.org"]')
    lines.append("  contracts: []")
    lines.append("")
    lines.append("output:")
    lines.append(f'  dir: {profile.output_dir}')
    lines.append(f"  language: {profile.language}")
    lines.append("  levels:")
    for level in LEVELS:
        marker = "true" if level in profile.levels else "false"
        note = "" if level in SUPPORTED_LEVELS else "   # pendiente de implementación"
        lines.append(f"    {level}: {marker}{note}")
    lines.append("  notation:")
    lines.append("    diagrams: mermaid")
    lines.append("    architecture: c4")
    lines.append("    api: openapi3.1")
    lines.append("")
    lines.append("acceptance:")
    lines.append("  thresholds:")
    lines.append(f"    accuracy: {profile.thresholds.accuracy}")
    lines.append(f"    completeness: {profile.thresholds.completeness}")
    lines.append(f"    attribution: {profile.thresholds.attribution}")
    lines.append(f"    conciseness: {profile.thresholds.conciseness}")
    lines.append("")
    lines.append(f"freshness:")
    lines.append(f"  ttl_days: {profile.ttl_days}")
    lines.append("")
    lines.append("learn:")
    lines.append(f"  promotion_delta: {profile.promotion_delta}")
    lines.append(f"  rollback_drop: {profile.rollback_drop}")
    lines.append(f"  federate: {'true' if profile.federate else 'false'}")
    if profile.glossary:
        lines.append("")
        lines.append("# Glosario de dominio: la palanca de mayor retorno medida (+0.525 de recall en")
        lines.append("# español). Sin él, «cadena de filtros» no se acerca a `securityFilterChain`.")
        lines.append("glossary:")
        for phrase, terms in profile.glossary.items():
            rendered = ", ".join(f'"{term}"' for term in terms)
            lines.append(f'  "{phrase}": [{rendered}]')
    return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class Change:
    """Una diferencia entre el perfil vigente y lo que la detección propone."""

    field: str
    before: object
    after: object
    reason: str
    applied: bool = True

    @property
    def kind(self) -> str:
        return "aplicado" if self.applied else "conservado"

    def describe(self) -> str:
        return f"{self.field}: {self.before!r} → {self.after!r} ({self.reason})"


#: Campos que **nunca** se pisan automáticamente: son decisiones humanas, no detección.
HUMAN_FIELDS = ("mode", "ttl_days", "thresholds", "output_dir", "language", "include", "federate")


def plan_changes(existing: Profile | None, proposed: Profile) -> list[Change]:
    """Orden de cambio: qué se actualizaría y qué se conserva, con su motivo.

    Regla: la detección solo puede **añadir** estructura observable (niveles nuevos, exclusiones
    nuevas, glosario si estaba vacío). Nunca redefine umbrales, modo, TTL ni vocabulario ya escrito.
    """
    if existing is None:
        return [Change("perfil", None, proposed.project, "no existía perfil: se crea completo")]

    changes: list[Change] = []

    added_levels = tuple(level for level in proposed.levels if level not in existing.levels)
    if added_levels:
        merged = tuple(level for level in LEVELS if level in (*existing.levels, *added_levels))
        reason = (
            "se detectaron rutas HTTP: habilita la guía de uso"
            if "l3" in added_levels
            else "niveles nuevos detectados"
        )
        changes.append(Change("output.levels", existing.levels, merged, reason))

    new_exclusions = tuple(item for item in DEFAULT_EXCLUDE if item not in existing.exclude)
    if new_exclusions:
        changes.append(
            Change(
                "sources.git.exclude",
                len(existing.exclude),
                len(existing.exclude) + len(new_exclusions),
                f"{len(new_exclusions)} patrones de higiene nuevos",
            )
        )

    if not existing.glossary and proposed.glossary:
        changes.append(
            Change("glossary", 0, len(proposed.glossary), "el framework detectado tiene glosario semilla")
        )
    elif existing.glossary and proposed.glossary and dict(existing.glossary) != dict(proposed.glossary):
        changes.append(
            Change("glossary", len(existing.glossary), len(existing.glossary), "se conserva el glosario humano", applied=False)
        )

    if existing.project != proposed.project:
        changes.append(
            Change("project", existing.project, existing.project, "el nombre es decisión del proyecto", applied=False)
        )

    for field_name in HUMAN_FIELDS:
        before = getattr(existing, field_name)
        after = getattr(proposed, field_name)
        if before != after:
            changes.append(
                Change(field_name, before, before, "valor humano: la detección no lo redefine", applied=False)
            )
    return changes


def merge(existing: Profile, proposed: Profile) -> Profile:
    """Perfil resultante: aplica solo los cambios marcados y preserva lo humano."""
    levels = tuple(level for level in LEVELS if level in (*existing.levels, *proposed.levels))
    exclusions = tuple(dict.fromkeys((*existing.exclude, *DEFAULT_EXCLUDE)))
    return replace(
        existing,
        levels=levels,
        exclude=exclusions,
        glossary=existing.glossary or proposed.glossary,
    )


def render_change_order(changes: Sequence[Change], project: str) -> str:
    """Orden de cambio en Markdown: numerada, con motivo y con lo que se conserva."""
    applied = [change for change in changes if change.applied]
    kept = [change for change in changes if not change.applied]
    lines = [
        f"# Orden de cambio de `init` · {project}",
        "",
        "Reejecutar `docu init` no sobrescribe decisiones humanas: propone y espera aprobación.",
        "",
        "## Cambios propuestos",
        "",
    ]
    if applied:
        for index, change in enumerate(applied, start=1):
            lines.append(f"{index}. **{change.field}**: {change.before!r} → {change.after!r} — {change.reason}")
    else:
        lines.append("_Ninguno: el perfil ya refleja lo detectado._")
    lines += ["", "## Conservado por decisión humana", ""]
    if kept:
        for change in kept:
            lines.append(f"- **{change.field}**: {change.before!r} — {change.reason}")
    else:
        lines.append("_Nada que conservar en esta corrida._")
    lines += [
        "",
        "Para aplicarlo: `docu init --apply` (o `--force` para regenerar desde cero).",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "DEFAULT_EXCLUDE",
    "LEVELS",
    "Change",
    "HUMAN_FIELDS",
    "Profile",
    "ProfileError",
    "SUPPORTED_LEVELS",
    "candidate_paths",
    "detect",
    "find",
    "from_dict",
    "load",
    "merge",
    "plan_changes",
    "propose",
    "render_change_order",
    "to_yaml",
]
