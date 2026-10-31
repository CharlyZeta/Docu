"""Pipeline de generacion: de los artefactos al documento, sin prosa inventada.

F1 entrega documento **extractivo y verificable**: hechos con cita, secciones declaradas como
hueco cuando no hay evidencia, y compuerta de calidad antes de escribir nada. F4 anade el estado
de frescura: cada pagina recuerda el hash de sus seis entradas y solo se regenera cuando cambia.
El LLM de F3 se enchufa detras de este mismo contrato: recibe los hechos y solo puede redactarlos.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from docu.adapters.langs.registry import adapter_for
from docu.core.contracts import (
    DocState,
    GateDecision,
    GateOutcome,
    Metrics,
    Mode,
    sha256_of,
    utcnow,
)
from docu.core.policy import GatePolicy, Thresholds
from docu.generate.facts import (
    Fact,
    package_facts,
    package_json_facts,
    pom_facts,
    pyproject_facts,
    pyproject_scripts_facts,
    requirements_facts,
    symbol_facts as java_facts,
    unsupported,
    yaml_facts,
)
from docu.generate.diagrams import build_all, write_diagrams
from docu.generate.markdown import RENDERERS
from docu.generate.ops import (
    compose_facts,
    dockerfile_facts,
    env_facts,
    is_compose_file,
    is_docker_file,
    is_env_file,
    is_workflow_file,
    scripts_facts,
    workflow_facts,
)
from docu.index.packages import detect_packages
from docu.index.manifest import (
    DEFAULT_VERSIONS,
    MANIFEST_PATH,
    DocEntry,
    Manifest,
    document_exists,
    fact_signature,
    input_hash_for,
    profile_digest,
    state_of,
)

EXCLUDED_PARTS = ("target", ".git", "node_modules", "build", "dist", ".sdd", ".agents", ".idea", ".venv")

#: Directorios de pruebas: no son API del producto. Se excluyen por defecto y `--include-tests`
#: los recupera. Sin esto, un proyecto con `tests/` en la raíz documenta sus propias aserciones.
TEST_DIRS = frozenset({"tests", "test", "__tests__", "spec", "specs"})


def _is_test_path(rel: Path) -> bool:
    lowered = [part.lower() for part in rel.parts]
    if any(part in TEST_DIRS for part in lowered):
        return True
    return "src" in lowered and "test" in lowered
LEVEL_FILENAMES = {
    "l1": "l1-manual-tecnico.md",
    "l2": "l2-operacion.md",
    "l3": "l3-guia-de-uso.md",
    "l4": "l4-readme.md",
}
EXTRA_FILES = ("package.json", "pyproject.toml", "requirements.txt")
DEFAULT_LEVELS = ("l1", "l4")


@dataclass(frozen=True, slots=True)
class GeneratedDoc:
    level: str
    path: Path
    content: str


@dataclass(frozen=True, slots=True)
class GenerationResult:
    project: str
    docs: tuple[GeneratedDoc, ...]
    facts: tuple[Fact, ...]
    sources: Mapping[str, str]
    metrics: Metrics
    gate: GateDecision
    elapsed_s: float
    unsupported: tuple[Fact, ...] = field(default_factory=tuple)
    states: Mapping[str, DocState] = field(default_factory=dict)
    manifest_path: Path | None = None
    applicability: Mapping[str, bool] = field(default_factory=dict)
    unsupported_languages: Mapping[str, int] = field(default_factory=dict)
    diagrams: tuple[str, ...] = field(default_factory=tuple)
    dry_run: bool = False

    @property
    def wrote_files(self) -> bool:
        return bool(self.docs) and not self.dry_run

    @property
    def pending(self) -> tuple[str, ...]:
        """Niveles que quedaron sin regenerar en modo incremental."""
        return tuple(
            level for level, state in self.states.items() if state is DocState.FRESH
        )


def _path_matches(rel: str, patterns: Sequence[str]) -> bool:
    """Coincidencia por segmento: `contracts/*` casa con `contracts/FEAT.md` y con sus hijos.

    Los comodines globales (`*`, `**`, `**/*`) casan con todo: es lo que un humano espera al
    escribirlos, y `fnmatch` no lo cumple para archivos de la raíz.
    """
    import fnmatch

    if any(pattern in ("*", "**", "**/*", "./**") for pattern in patterns):
        return True
    parts = rel.split("/")
    for index in range(1, len(parts) + 1):
        candidate = "/".join(parts[:index])
        if any(fnmatch.fnmatch(candidate, pattern) or fnmatch.fnmatch(rel, pattern) for pattern in patterns):
            return True
    return False


def _effective_exclude(exclude: Sequence[str]) -> tuple[str, ...]:
    """Exclusiones del proyecto + piso de higiene + `.gitignore`.

    El `.gitignore` es la declaración más autorizada de qué no es fuente: sin leerlo, un proyecto
    indexaba `coverage/` (artefactos de reportes) y lo contaba como código en sus métricas.
    """
    from docu.core.profile import DEFAULT_EXCLUDE

    return tuple(dict.fromkeys((*exclude, *DEFAULT_EXCLUDE)))


def _discover(
    root: Path,
    include_tests: bool = False,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> dict[str, Path]:
    """Archivos relevantes, con la higiene de corpus que declare el perfil."""
    from docu.index.ignore import is_ignored, load as load_ignore

    patterns = _effective_exclude(exclude)
    rules = load_ignore(root)
    found: dict[str, Path] = {}
    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file():
            continue
        rel = candidate.relative_to(root)
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
        name = candidate.name
        if (
            adapter_for(name) is not None
            or name.endswith((".yml", ".yaml"))
            or name == "pom.xml"
            or name in EXTRA_FILES
            or is_env_file(rel_text)
            or is_docker_file(rel_text)
            or is_compose_file(rel_text)
        ):
            found[rel_text] = candidate
    return found


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def collect_facts(
    root: Path,
    include_tests: bool = False,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> tuple[list[Fact], dict[str, str]]:
    """Recorre el repositorio y devuelve hechos + huellas de las fuentes.

    El despacho es por adaptador: anadir un lenguaje no toca esta funcion mas alla del registro.
    """
    facts: list[Fact] = []
    sources: dict[str, str] = {}
    discovered = _discover(root, include_tests=include_tests, include=include, exclude=exclude)
    for rel, path in discovered.items():
        source = _read(path)
        # Hash sobre contenido normalizado: si no, el mismo commit da hashes distintos en Windows
        # (CRLF) y en Linux (LF), y la frescura se rompe al mover el proyecto o al correr el CI.
        normalized = source.replace("\r\n", "\n").replace("\r", "\n")
        sources[rel] = sha256_of(normalized.encode("utf-8")).replace("sha256:", "")[:12]
        adapter = adapter_for(rel)
        if is_compose_file(rel):
            facts.extend(compose_facts(rel, source))
        elif is_env_file(rel):
            # Sólo archivos de ejemplo: un `.env` real no se abre nunca.
            facts.extend(env_facts(rel, source))
        elif is_docker_file(rel):
            facts.extend(dockerfile_facts(rel, source))
        elif is_workflow_file(rel) and rel.endswith((".yml", ".yaml")):
            # Los workflows son CI, no configuración de la aplicación: mezclarlos ensucia la tabla
            # de configuración con claves internas de GitHub Actions.
            facts.extend(workflow_facts(rel, source))
        elif adapter is not None:
            facts.extend(java_facts(adapter.symbols(rel, source)))  # type: ignore[attr-defined]
        elif rel.endswith("pom.xml"):
            facts.extend(pom_facts(rel, source))
        elif rel.endswith((".yml", ".yaml")):
            facts.extend(yaml_facts(rel, source))
        elif rel.endswith("package.json"):
            facts.extend(package_json_facts(rel, source))
            try:
                payload = json.loads(source)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                facts.extend(scripts_facts(rel, payload, source))
        elif rel.endswith("pyproject.toml"):
            facts.extend(pyproject_facts(rel, source))
            facts.extend(pyproject_scripts_facts(rel, source))
        elif rel.endswith("requirements.txt"):
            facts.extend(requirements_facts(rel, source))
    facts.extend(package_facts(detect_packages(discovered)))

    # PDFs como fuentes citables: la unidad de cita es la página. Su huella entra en `sources`
    # para que un PDF nuevo o modificado invalide la frescura, igual que un archivo de código.
    from docu.index.pdfdocs import load_all

    documents, _texts, digests = load_all(root, include=include, exclude=exclude, include_tests=include_tests)
    sources.update(digests)
    facts.extend(document.to_fact() for document in documents)

    # Fuentes web congeladas: se leen del índice local, nunca de la red. La generación debe dar el
    # mismo resultado sin conexión; refrescar es una decisión explícita (`docu web --fetch`).
    from docu.core.profile import find as find_profile, load as load_profile
    from docu.index.webdocs import load_documents

    profile_path = find_profile(root)
    profile = load_profile(profile_path) if profile_path else None
    web_urls = profile.web_urls if profile else ()
    for document in load_documents(root, web_urls):
        if document.rel and document.usable:
            facts.append(document.to_fact())
            snapshot = root / document.rel
            if snapshot.is_file():
                sources[document.rel] = sha256_of(
                    snapshot.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
                ).replace("sha256:", "")[:12]
    return facts, sources


#: Pistas de que el proyecto *debería* exponer rutas HTTP. Si aparecen y no hay rutas
#: extraídas, la completitud baja: es una sospecha de fallo del adaptador, no una ausencia legítima.
FRAMEWORK_HINTS = (
    "spring-boot-starter-web",
    "spring-boot-starter-security",
    "springdoc",
    "fastapi",
    "flask",
    "django",
    "starlette",
    "express",
    "fastify",
    "koa",
    "@nestjs/core",
    "@nestjs/common",
)

MANIFESTS = ("pom.xml", "build.gradle", "build.gradle.kts", "pyproject.toml", "package.json", "requirements.txt")

#: Lenguajes que el producto reconoce **como código** pero aun no sabe documentar. Se informan en
#: lugar de ignorarse: un silencio se confunde con «este proyecto no tiene nada que documentar».
UNSUPPORTED_SOURCES = {
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".kt": "Kotlin",
    ".scala": "Scala",
    ".swift": "Swift",
    ".c": "C",
    ".h": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".ex": "Elixir",
    ".dart": "Dart",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".sol": "Solidity",
}


def unsupported_sources(
    root: Path,
    include_tests: bool = False,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> dict[str, int]:
    """Cuenta archivos de lenguajes conocidos pero no soportados, por extension."""
    from docu.index.ignore import is_ignored, load as load_ignore

    patterns = _effective_exclude(exclude)
    rules = load_ignore(root)
    counts: dict[str, int] = {}
    for candidate in root.rglob("*"):
        if not candidate.is_file():
            continue
        rel = candidate.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in rel.parts):
            continue
        if is_ignored(rel.as_posix(), rules):
            continue
        if patterns and _path_matches(rel.as_posix(), patterns):
            continue
        if include and not _path_matches(rel.as_posix(), include):
            continue
        if not include_tests and _is_test_path(rel):
            continue
        suffix = candidate.suffix.lower()
        if suffix in UNSUPPORTED_SOURCES:
            counts[suffix] = counts.get(suffix, 0) + 1
    return dict(sorted(counts.items()))


def applicability(facts: Sequence[Fact], root: Path) -> dict[str, bool]:
    """¿Qué secciones tienen sentido en **este** proyecto?

    Un CLI en Python no tiene módulos Maven ni rutas HTTP: exigírselos convierte la compuerta en
    ruido y penaliza proyectos legítimos. La aplicabilidad se deduce de artefactos observables y
    queda declarada en el documento, no escondida en el código.
    """
    kinds = {fact.kind for fact in facts}
    dependencies = " ".join(
        fact.subject.lower() for fact in facts if fact.kind == "dependency"
    )
    has_structure = "module" in kinds or "package" in kinds
    return {
        "type": "type" in kinds,
        "config_key": "config_key" in kinds,
        "dependency": "dependency" in kinds or any((root / name).exists() for name in MANIFESTS),
        "module": has_structure,
        "route": "route" in kinds or any(hint in dependencies for hint in FRAMEWORK_HINTS),
    }


#: Qué hechos cuentan como evidencia de cada sección. Un paquete es la unidad arquitectónica de
#: Python/TS igual que un módulo Maven lo es de Java: exigir `module` a un proyecto Python penaliza
#: algo que no puede tener.
KIND_EVIDENCE: dict[str, tuple[str, ...]] = {
    "module": ("module", "package"),
}


def completeness(facts: Sequence[Fact], applicable: Mapping[str, bool]) -> float:
    """Cobertura de las secciones **aplicables**: 10 si todo lo que existe está documentado."""
    required = [kind for kind, needed in applicable.items() if needed]
    if not required:
        return 0.0
    present = sum(
        1
        for kind in required
        if any(fact.kind in KIND_EVIDENCE.get(kind, (kind,)) for fact in facts)
    )
    return round(10.0 * present / len(required), 2)


def conciseness(facts: Sequence[Fact]) -> float:
    """Penaliza duplicados exactos (misma afirmacion, misma cita)."""
    if not facts:
        return 0.0
    unique = {(fact.kind, fact.subject, fact.detail, fact.citation) for fact in facts}
    return round(10.0 * len(unique) / len(facts), 2)


LANGUAGE_BY_SUFFIX = {
    ".java": "java",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
}


def _detected_languages(sources: Mapping[str, str]) -> str:
    languages = {
        language
        for path in sources
        for suffix, language in LANGUAGE_BY_SUFFIX.items()
        if path.endswith(suffix)
    }
    return ",".join(sorted(languages))


def _record_run(
    *,
    root: Path,
    project: str,
    metrics: Metrics,
    gate: GateDecision,
    states: Mapping[str, DocState],
    versions: Mapping[str, str],
    sources: Mapping[str, str],
    pages_written: int,
    elapsed_s: float,
    ledger_dir: Path | None = None,
) -> None:
    """Deja constancia en el ledger. Un ledger no escribible no puede tumbar la generación.

    Con `--manifest` fuera del proyecto, el ledger se escribe junto al manifest: una prueba sobre un
    repositorio ajeno no debe dejar rastros dentro de él.
    """
    from docu.learn import ledger

    try:
        ledger.append(
            ledger.ledger_file(ledger_dir or root),
            project=project,
            metrics=metrics,
            gate=gate,
            mode=Mode.APPLY,
            states={level: state.value for level, state in states.items()},
            versions={**versions, "languages": _detected_languages(sources)},
            pages_written=pages_written,
            pages_skipped=max(0, len(states) - pages_written),
            elapsed_s=elapsed_s,
        )
    except OSError:
        pass


def _language_names(counts: Mapping[str, int]) -> dict[str, int]:
    """Agrupa conteos por extension bajo el nombre del lenguaje (`C` puede venir de .c y .h)."""
    grouped: dict[str, int] = {}
    for suffix, count in counts.items():
        name = UNSUPPORTED_SOURCES.get(suffix, suffix)
        grouped[name] = grouped.get(name, 0) + count
    return dict(sorted(grouped.items()))


def manifest_file(root: Path, manifest_path: Path | str | None) -> Path:
    return Path(manifest_path) if manifest_path else root / MANIFEST_PATH


def inspect(
    root: Path | str,
    levels: Sequence[str] = DEFAULT_LEVELS,
    manifest_path: Path | str | None = None,
    include_tests: bool = False,
    ttl_days: int = 90,
    version: str = "0.1.0",
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> tuple[Manifest | None, dict[str, DocState], dict[str, str]]:
    """Estado de frescura sin generar nada. Es lo que consulta el CI en cada PR.

    Usa **el mismo descubrimiento** que `generate`: si no, los hashes divergen y la frescura miente.
    """
    root_path = Path(root).resolve()
    manifest = Manifest.load(manifest_file(root_path, manifest_path))
    facts, sources = collect_facts(root_path, include_tests=include_tests, include=include, exclude=exclude)
    versions = {**DEFAULT_VERSIONS, "docu": version}
    signature = fact_signature(facts)
    digest = profile_digest(root_path)
    states: dict[str, DocState] = {}
    hashes: dict[str, str] = {}
    for level in levels:
        current = input_hash_for(
            level=level,
            sources=sources,
            fact_signature=signature,
            versions=versions,
            profile_digest=digest,
        )
        hashes[level] = current
        entry = manifest.entry(level) if manifest else None
        states[level] = state_of(
            entry=entry,
            current_hash=current,
            ttl_days=ttl_days,
            file_exists=document_exists(entry, root_path),
        )
    return manifest, states, hashes


def collect_all_facts(
    root_path: Path,
    include_tests: bool = False,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    project: str | None = None,
) -> tuple[list[Fact], dict[str, str], dict[str, Path], "object"]:
    """Hechos completos: código, configuración, fuentes externas, intención y decisiones.

    Una sola puerta para que `gen`, `prose` y la auditoría hablen del **mismo** universo. Antes, la
    prosa delegada ofrecía hechos de código pero no de intención, y el agente citaba ids inexistentes.
    """
    from docu.generate.narrative import collect as collect_narrative

    facts, sources = collect_facts(
        root_path, include_tests=include_tests, include=include, exclude=exclude
    )
    discovered = _discover(root_path, include_tests=include_tests, include=include, exclude=exclude)
    kind_counts: dict[str, int] = {}
    for fact in facts:
        kind_counts[fact.kind] = kind_counts.get(fact.kind, 0) + 1
    narrative = collect_narrative(
        root_path, discovered, kind_counts, project or root_path.name, _read
    )
    facts.extend(narrative.facts)
    return facts, sources, discovered, narrative


def collect_all_facts_only(
    root_path: Path,
    include_tests: bool = False,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    project: str | None = None,
) -> list[Fact]:
    """Variante para comandos que sólo necesitan la lista (prosa delegada, auditoría)."""
    facts, _sources, _discovered, _narrative = collect_all_facts(
        root_path, include_tests=include_tests, include=include, exclude=exclude, project=project
    )
    return facts


def generate(
    root: Path | str,
    out_dir: Path | str,
    levels: Sequence[str] = DEFAULT_LEVELS,
    project: str | None = None,
    version: str = "0.1.0",
    include_tests: bool = False,
    stamp: bool = False,
    incremental: bool = False,
    manifest_path: Path | str | None = None,
    ttl_days: int = 90,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    thresholds: Thresholds | None = None,
    dry_run: bool = False,
) -> GenerationResult:
    """Genera los niveles pedidos. No escribe nada si la compuerta dura falla.

    `dry_run=True` calcula hechos, métricas y compuerta pero **no escribe nada**: ni documentos, ni
    manifest, ni diagramas, ni ledger. Existe para probar el agente sobre un repositorio ajeno sin
    dejar rastro.
    """
    started = time.perf_counter()
    root_path = Path(root).resolve()
    out_path = Path(out_dir)
    name = project or root_path.name
    manifest_target = manifest_file(root_path, manifest_path)

    facts, sources, discovered, narrative = collect_all_facts(
        root_path,
        include_tests=include_tests,
        include=include,
        exclude=exclude,
        project=name,
    )
    packages = detect_packages(discovered)
    diagrams = build_all(discovered, packages, facts, _read)

    # Prosa delegada: si el agente del desarrollador dejó una respuesta validada, entra al documento
    # con su procedencia. Se revalida contra los hechos actuales: la prosa de ayer puede citar un
    # símbolo que hoy ya no existe.
    from docu.generate import prose as prose_module

    prose_markdown = ""
    prose_meta: dict[str, str] = {}
    stored = prose_module.load(root_path)
    if stored is not None:
        response, verdict = stored
        validated, index = prose_module.validate(
            {"reviewer": response.reviewer, "sections": response.sections}, facts
        )
        if validated.accepted:
            prose_markdown = prose_module.render(validated, index)
            prose_meta["prose_reviewer"] = validated.reviewer
            if verdict is not None:
                prose_meta["prose_judge"] = verdict.judge
                prose_meta["prose_score"] = f"{verdict.score:.1f}"
        else:
            prose_meta["prose_error"] = "; ".join(validated.errors[:2])

    missing = unsupported(facts)
    digest = sha256_of("|".join(f"{path}:{sha}" for path, sha in sorted(sources.items())))[:12]
    versions = {**DEFAULT_VERSIONS, "docu": version}
    signature = fact_signature(facts)
    profile = profile_digest(root_path)
    manifest = Manifest.load(manifest_target) or Manifest(project=name, versions=versions)
    manifest.project = name
    manifest.versions = versions

    applicable = applicability(facts, root_path)
    languages = unsupported_sources(
        root_path, include_tests=include_tests, include=include, exclude=exclude
    )
    metrics = Metrics(
        accuracy=10.0,
        completeness=completeness(facts, applicable),
        attribution=10.0 if not missing else 0.0,
        conciseness=conciseness(facts),
        freshness=10.0,
        cost_usd=0.0,
        unsupported_claims=len(missing),
    )
    gate = GatePolicy(thresholds=thresholds or Thresholds()).evaluate(metrics, Mode.APPLY)

    # Compuerta dura propia: sin hechos no hay documento. Escribir Markdown vacío con secciones
    # «sin evidencia» es ruido, no documentación.
    if not facts:
        reason = "no se detectó nada documentable"
        if languages:
            detail = ", ".join(f"{name} ({count})" for name, count in _language_names(languages).items())
            reason += f"; lenguajes no soportados: {detail}"
        gate = GateDecision(GateOutcome.ABORT, (reason,))

    meta = {
        "version": version,
        "generated_at": utcnow().isoformat(timespec="seconds") if stamp else "",
        "digest": digest,
        "sources": str(len(sources)),
        "unsupported": str(len(missing)),
        "applicable": ", ".join(kind for kind, needed in applicable.items() if needed),
        "not_applicable": ", ".join(kind for kind, needed in applicable.items() if not needed),
        "intro": narrative.intro,
        "prose": prose_markdown,
        **prose_meta,
        "unsupported_languages": ", ".join(
            f"{name} ({count})" for name, count in _language_names(languages).items()
        ),
    }

    docs: list[GeneratedDoc] = []
    states: dict[str, DocState] = {}
    for level in levels:
        current_hash = input_hash_for(
            level=level,
            sources=sources,
            fact_signature=signature,
            versions=versions,
            profile_digest=profile,
        )
        entry = manifest.entry(level)
        state = state_of(
            entry=entry,
            current_hash=current_hash,
            ttl_days=ttl_days,
            file_exists=document_exists(entry, root_path),
        )
        states[level] = state
        if incremental and state is DocState.FRESH:
            continue
        if gate.outcome is GateOutcome.ABORT:
            continue
        renderer = RENDERERS[level]
        content = renderer(name, facts, sources, meta, diagrams=diagrams)
        filename = LEVEL_FILENAMES.get(level, f"{level}.md")
        destination = out_path / filename
        if dry_run:
            # Se renderiza para validar que la compuerta y el render funcionan, pero no se escribe.
            docs.append(GeneratedDoc(level=level, path=destination, content=content))
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        docs.append(GeneratedDoc(level=level, path=destination, content=content))
        manifest.upsert(
            DocEntry(
                level=level,
                path=destination.relative_to(root_path).as_posix()
                if destination.is_relative_to(root_path)
                else str(destination),
                input_hash=current_hash,
                generated_at=utcnow().isoformat(timespec="seconds"),
                content_hash=sha256_of(content),
                ttl_days=ttl_days,
                sources=dict(sources),
            )
        )

    if not dry_run and gate.outcome is not GateOutcome.ABORT:
        manifest.save(manifest_target)
        write_diagrams(diagrams, out_path / "diagrams")

    if not dry_run:
        _record_run(
            root=root_path,
            project=name,
            metrics=metrics,
        gate=gate,
        states=states,
        versions=versions,
        sources=sources,
        pages_written=len(docs),
        elapsed_s=time.perf_counter() - started,
        ledger_dir=(manifest_target.parent if manifest_path else None),
    )

    return GenerationResult(
        project=name,
        docs=tuple(docs),
        facts=tuple(facts),
        sources=sources,
        metrics=metrics,
        gate=gate,
        elapsed_s=time.perf_counter() - started,
        unsupported=tuple(missing),
        states=states,
        manifest_path=manifest_target,
        applicability=applicable,
        unsupported_languages=_language_names(languages),
        diagrams=tuple(diagram.filename for diagram in diagrams),
        dry_run=dry_run,
    )
