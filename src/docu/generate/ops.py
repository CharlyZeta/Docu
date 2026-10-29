"""Hechos de operación y despliegue (Nivel 2).

Tres reglas que definen este módulo:

1. **Nunca se documentan valores de secretos.** De `.env.example` se toman los *nombres* de las
   variables, jamás los valores: un documento que copia una clave es un incidente de seguridad, no
   documentación.
2. **Sólo archivos de ejemplo.** Se leen `.env.example` / `.env.sample` / `.env.template`; un `.env`
   real no se abre nunca.
3. **Cada línea con su cita.** Un procedimiento de despliegue sin archivo y línea no es un
   procedimiento, es un rumor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from docu.core.yamlmini import YamlError, parse as parse_yaml
from docu.generate.facts import Fact, _line_with, _line_with_after

ENV_FILES = (".env.example", ".env.sample", ".env.template", ".env.dist")
DOCKER_FILES = ("Dockerfile", "Dockerfile.dev", "Dockerfile.prod", "dockerfile")
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")

_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=")
_FROM_RE = re.compile(r"^\s*FROM\s+(?P<image>\S+)", re.IGNORECASE)
_EXPOSE_RE = re.compile(r"^\s*EXPOSE\s+(?P<ports>.+)$", re.IGNORECASE)
_CMD_RE = re.compile(r"^\s*(?P<directive>CMD|ENTRYPOINT)\s+(?P<command>.+)$", re.IGNORECASE)
_PORT_MAPPING_RE = re.compile(r"^[\"']?(?P<host>\d+):(?P<container>\d+)")


def is_env_file(path: str) -> bool:
    return path.rsplit("/", 1)[-1] in ENV_FILES


def is_docker_file(path: str) -> bool:
    return path.rsplit("/", 1)[-1] in DOCKER_FILES


def is_compose_file(path: str) -> bool:
    return path.rsplit("/", 1)[-1] in COMPOSE_FILES


def is_workflow_file(path: str) -> bool:
    """Workflows de CI: no son configuración de la aplicación y no deben aparecer como tal."""
    return "/.github/workflows/" in f"/{path}" or path.startswith(".github/workflows/")


def env_facts(path: str, source: str) -> list[Fact]:
    """Variables de entorno **requeridas**, por nombre. El valor no se lee ni se documenta."""
    facts: list[Fact] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        if line.strip().startswith("#"):
            continue
        match = _ENV_LINE_RE.match(line)
        if match is None:
            continue
        name = match.group("key")
        facts.append(
            Fact(
                kind="env_var",
                subject=name,
                detail=path.rsplit("/", 1)[-1],
                citation=f"{path}#L{line_number}-L{line_number}",
                attributes={"file": path},
            )
        )
    return facts


def dockerfile_facts(path: str, source: str) -> list[Fact]:
    """Imagen base, puertos expuestos y comando de arranque."""
    facts: list[Fact] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if match := _FROM_RE.match(line):
            facts.append(
                Fact(
                    kind="image",
                    subject=match.group("image"),
                    detail="imagen base",
                    citation=f"{path}#L{line_number}-L{line_number}",
                )
            )
        elif match := _EXPOSE_RE.match(line):
            for port in match.group("ports").split():
                facts.append(
                    Fact(
                        kind="port",
                        subject=port,
                        detail="expuesto por la imagen",
                        citation=f"{path}#L{line_number}-L{line_number}",
                    )
                )
        elif match := _CMD_RE.match(line):
            facts.append(
                Fact(
                    kind="process",
                    subject=f"{match.group('directive').upper()} {match.group('command').strip()[:80]}",
                    detail="arranque del contenedor",
                    citation=f"{path}#L{line_number}-L{line_number}",
                )
            )
    return facts


def _safe_parse(source: str) -> object:
    """YAML tolerante: un compose exótico no debe tumbar la generación completa."""
    try:
        return parse_yaml(source)
    except YamlError:
        return None


def compose_facts(path: str, source: str) -> list[Fact]:
    """Servicios, puertos publicados y variables de entorno (sólo nombres)."""
    payload = _safe_parse(source)
    if not isinstance(payload, dict):
        return []
    services = payload.get("services")
    if not isinstance(services, dict):
        return []
    facts: list[Fact] = []
    for service in services:
        name = str(service)
        facts.append(
            Fact(
                kind="service",
                subject=name,
                detail="servicio de compose",
                citation=f"{path}#L{_line_with(source, f'{name}:')}-L{_line_with(source, f'{name}:')}",
            )
        )
        block = services[service]
        if not isinstance(block, dict):
            continue
        for port in block.get("ports") or []:
            match = _PORT_MAPPING_RE.match(str(port))
            if match is None:
                continue
            facts.append(
                Fact(
                    kind="port",
                    subject=f"{match.group('host')}→{match.group('container')}",
                    detail=f"publicado por {name}",
                    citation=f"{path}#L{_line_with(source, str(port))}-L{_line_with(source, str(port))}",
                )
            )
        depends = block.get("depends_on") or []
        if isinstance(depends, list):
            for dependency in depends:
                facts.append(
                    Fact(
                        kind="dependency_edge",
                        subject=f"{name} → {dependency}",
                        detail="orden de arranque",
                        citation=f"{path}#L{_line_with_after(source, str(dependency), source.find('depends_on'))}"
                        f"-L{_line_with_after(source, str(dependency), source.find('depends_on'))}",
                    )
                )
    return facts


def scripts_facts(path: str, payload: dict[str, object], source: str) -> list[Fact]:
    """Comandos declarados en `package.json` (`scripts`)."""
    scripts = payload.get("scripts")
    if not isinstance(scripts, dict):
        return []
    start = source.find('"scripts"')
    facts: list[Fact] = []
    for name, command in scripts.items():
        line = _line_with_after(source, f'"{name}"', start)
        facts.append(
            Fact(
                kind="command",
                subject=str(name),
                detail=str(command)[:120],
                citation=f"{path}#L{line}-L{line}",
            )
        )
    return facts


def workflow_facts(path: str, source: str) -> list[Fact]:
    """Nombre, disparadores y jobs de un workflow de CI."""
    payload = _safe_parse(source)
    if not isinstance(payload, dict):
        return []
    facts: list[Fact] = []
    name = payload.get("name") or path.rsplit("/", 1)[-1]
    facts.append(
        Fact(
            kind="workflow",
            subject=str(name),
            detail=path,
            citation=f"{path}#L1-L1",
        )
    )
    triggers = payload.get("on") or payload.get(True)  # `on:` se parsea como booleano en YAML 1.1
    if isinstance(triggers, str):
        triggers = [triggers]
    elif isinstance(triggers, dict):
        triggers = list(triggers)
    if isinstance(triggers, list):
        on_start = source.find("on:")
        for trigger in triggers:
            # La cita debe apuntar a la línea del disparador, no a la clave `on:`: si no, la
            # auditoría tiene razón en marcarla y el lector no encuentra nada al abrirla.
            line = _line_with_after(source, f"{trigger}", on_start if on_start >= 0 else 0)
            facts.append(
                Fact(
                    kind="trigger",
                    subject=str(trigger),
                    detail=f"dispara {name}",
                    citation=f"{path}#L{line}-L{line}",
                )
            )
    jobs = payload.get("jobs")
    if isinstance(jobs, dict):
        start = source.find("jobs:")
        for job in jobs:
            line = _line_with_after(source, f"{job}:", start)
            facts.append(
                Fact(
                    kind="ci_job",
                    subject=str(job),
                    detail=f"job de {name}",
                    citation=f"{path}#L{line}-L{line}",
                )
            )
    return facts


__all__ = [
    "COMPOSE_FILES",
    "DOCKER_FILES",
    "ENV_FILES",
    "compose_facts",
    "dockerfile_facts",
    "env_facts",
    "is_compose_file",
    "is_docker_file",
    "is_env_file",
    "is_workflow_file",
    "scripts_facts",
    "workflow_facts",
]
