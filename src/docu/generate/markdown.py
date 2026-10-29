"""Renderizado Markdown de los niveles de documentacion.

Regla visible en la salida: **cada fila lleva su cita** y una seccion sin evidencia se declara
como hueco. Un documento generado que se inventa una seccion es peor que uno que admite que no
sabe: el segundo se puede corregir.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from docu.generate.facts import Fact

NO_EVIDENCE = (
    "> **Sin evidencia disponible.** Esta sección no se documenta: el agente no rellena huecos "
    "con prosa plausible."
)

#: Marca estable para detectar huecos declarados (la usa el servidor MCP y la auditoría).
NO_EVIDENCE_MARKER = "Sin evidencia"


def _cite(citation: str) -> str:
    return f"`{citation}`"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    if not rows:
        return NO_EVIDENCE
    head = "| " + " | ".join(headers) + " |"
    rule = "|" + "|".join("---" for _ in headers) + "|"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([head, rule, *body])


def _by_kind(facts: Sequence[Fact], kind: str) -> list[Fact]:
    return [fact for fact in facts if fact.kind == kind]


def _dedupe(facts: Sequence[Fact]) -> list[Fact]:
    """Quita afirmaciones repetidas conservando la primera cita (los parents se repiten por modulo)."""
    seen: set[tuple[str, str, str]] = set()
    out: list[Fact] = []
    for fact in facts:
        key = (fact.kind, fact.subject, fact.detail)
        if key in seen:
            continue
        seen.add(key)
        out.append(fact)
    return out


def _counts(facts: Sequence[Fact]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for fact in facts:
        counts[fact.kind] = counts.get(fact.kind, 0) + 1
    return counts


def _header(
    project: str,
    title: str,
    meta: Mapping[str, str],
    facts: Sequence[Fact],
    plain: bool = False,
) -> list[str]:
    """Cabecera comun. En Nivel 3 se omite la huella técnica: no aporta a esa audiencia."""
    if plain:
        return [
            f"# {project} — {title}",
            "",
            f"Generado por `docu {meta.get('version', '0.1.0')}` a partir de las acciones y la "
            "configuración vigentes.",
            "",
            "> Cada dato de esta guía indica de dónde sale. Lo que no está declarado no se inventa.",
            "",
        ]
    counts = _counts(facts)
    stamp = f" el {meta['generated_at']}" if meta.get("generated_at") else ""
    return [
        f"# {project} — {title}",
        "",
        f"Generado por `docu {meta.get('version', '0.1.0')}`{stamp} · "
        f"fuente `{meta.get('digest', '—')}` · "
        f"archivos: {meta.get('sources', '0')} · "
        f"afirmaciones: {len(facts)} · sin cita: {meta.get('unsupported', '0')}",
        "",
        "> Documento **extractivo**: cada fila procede de un archivo y un rango de líneas del "
        "repositorio. No hay texto generado sin evidencia.",
        "",
    ]


def _diagrams_block(diagrams: Sequence[object], facts: Sequence[Fact]) -> list[str]:
    """Bloques Mermaid embebidos. Sin diagramas, se declara el hueco con su motivo."""
    blocks: list[str] = []
    for diagram in diagrams:
        name = getattr(diagram, "name", "")
        kind = getattr(diagram, "kind", "")
        mermaid = getattr(diagram, "mermaid", "")
        note = getattr(diagram, "note", "")
        if not mermaid:
            continue
        title = {
            "architecture": "Dependencias entre paquetes",
            "classes": "Clases del paquete",
            "api": "Flujo de la API",
        }.get(str(kind), str(name))
        blocks += [f"### {title}" + (f" · {note}" if note else ""), "", "```mermaid", mermaid, "```", ""]
    if not blocks:
        blocks += [
            NO_EVIDENCE,
            "",
            "> No se generan diagramas de secuencia: el grafo de llamadas no resuelve despacho "
            "dinámico (inyección de dependencias, interfaces), y un diagrama de secuencia inventado "
            "sería peor que su ausencia.",
            "",
        ]
    return blocks


# --------------------------------------------------------------------------- Nivel 1


def render_l1(
    project: str,
    facts: Sequence[Fact],
    sources: Mapping[str, str],
    meta: Mapping[str, str],
    diagrams: Sequence[object] = (),
) -> str:
    """Manual tecnico interno: arquitectura, diagramas, API, configuracion y simbolos."""
    lines = _header(project, "Manual técnico (Nivel 1)", meta, facts)
    counts = _counts(facts)

    lines += ["## 1. Resumen", ""]
    lines += [
        f"- Módulos de build: **{counts.get('module', 0)}** · paquetes: **{counts.get('package', 0)}**",
        f"- Dependencias declaradas: **{counts.get('dependency', 0)}**",
        f"- Rutas HTTP: **{counts.get('route', 0)}**",
        f"- Claves de configuración: **{counts.get('config_key', 0)}**",
        f"- Tipos: **{counts.get('type', 0)}** · métodos: **{counts.get('method', 0)}**",
        "",
    ]

    lines += ["## 2. Arquitectura: módulos y paquetes", ""]
    module_rows = [
        [f"`{fact.subject}`", fact.detail, _cite(fact.citation)]
        for fact in _by_kind(facts, "module")
    ]
    package_rows = [
        [
            f"`{fact.subject}`",
            fact.attributes.get("language", "—"),
            fact.attributes.get("files", "—"),
            _cite(fact.citation),
        ]
        for fact in _by_kind(facts, "package")
    ]
    if module_rows:
        lines += [_table(["Módulo de build", "Origen", "Cita"], module_rows), ""]
    if package_rows:
        lines += [_table(["Paquete", "Lenguaje", "Archivos", "Cita"], package_rows), ""]
    if not module_rows and not package_rows:
        lines += [NO_EVIDENCE, ""]

    lines += ["## 3. Diagramas", ""]
    lines += _diagrams_block(diagrams, facts)

    parent = _dedupe(_by_kind(facts, "parent"))
    properties = _dedupe(_by_kind(facts, "property"))
    if parent or properties:
        lines += ["### Plataforma", ""]
        rows = [["Parent", f"`{f.subject}`", f.detail, _cite(f.citation)] for f in parent]
        rows += [[f"`{f.subject}`", "propiedad", f.detail, _cite(f.citation)] for f in properties]
        lines += [_table(["Elemento", "Tipo", "Valor", "Cita"], rows), ""]

    lines += ["## 4. Dependencias", ""]
    lines += [
        _table(
            ["Artefacto", "Versión", "Scope", "Cita"],
            [
                [f"`{fact.subject}`", fact.detail, fact.attributes.get("scope", "—"), _cite(fact.citation)]
                for fact in _by_kind(facts, "dependency")
            ],
        ),
        "",
    ]

    lines += ["## 5. API HTTP", ""]
    lines += [
        _table(
            ["Verbo", "Ruta", "Handler", "Cita"],
            [
                [
                    fact.attributes.get("verb", "—"),
                    f"`{fact.attributes.get('path', '—')}`",
                    f"`{fact.attributes.get('handler', fact.detail)}`",
                    _cite(fact.citation),
                ]
                for fact in _by_kind(facts, "route")
            ],
        ),
        "",
    ]

    lines += ["## 6. Configuración", ""]
    lines += [
        _table(
            ["Clave", "Valor", "Cita"],
            [
                [f"`{fact.attributes.get('key', fact.subject)}`", f"`{fact.detail}`", _cite(fact.citation)]
                for fact in _by_kind(facts, "config_key")
            ],
        ),
        "",
    ]

    lines += ["## 7. Tipos", ""]
    lines += [
        _table(
            ["Tipo", "Nombre", "Anotaciones", "Cita"],
            [
                [
                    fact.detail,
                    f"`{fact.subject}`",
                    ", ".join(f"`{item}`" for item in fact.attributes.get("annotations", "—").split())
                    if fact.attributes.get("annotations", "—") != "—"
                    else "—",
                    _cite(fact.citation),
                ]
                for fact in _by_kind(facts, "type")
            ],
        ),
        "",
    ]

    lines += ["## 8. Índice de métodos", ""]
    methods = _by_kind(facts, "method")
    rows = [
        [f"`{fact.subject}`", f"`{(fact.detail or '')[:90]}`", _cite(fact.citation)] for fact in methods[:200]
    ]
    lines += [_table(["Símbolo", "Firma", "Cita"], rows), ""]
    if len(methods) > 200:
        lines += [f"_({len(methods) - 200} métodos adicionales omitidos del índice)_.", ""]

    lines += ["## 9. Alcance y límites", ""]
    lines += [
        "Secciones aplicables a este proyecto (y por tanto exigibles en la compuerta): "
        f"**{meta.get('applicable', '—') or '—'}**.",
        "",
        "Secciones **no aplicables** —no existen en este proyecto y no se penalizan—: "
        f"{meta.get('not_applicable', '—') or '—'}.",
        "",
    ]
    if meta.get("unsupported_languages"):
        lines += [
            f"**Lenguajes no soportados** presentes en el proyecto: "
            f"{meta['unsupported_languages']}. Esos archivos no se documentan: el generador los "
            "declara en lugar de ignorarlos.",
            "",
        ]
    lines += [
        "No cubierto todavía por el generador: diagramas de secuencia (el grafo de llamadas no "
        "resuelve despacho dinámico), diccionario de datos/ERD, contratos OpenAPI si no están "
        "declarados, e infraestructura provisionada (Terraform/CloudFormation). Los diagramas de "
        "componentes, clases y flujo de API están en la sección 3; la operación y el despliegue, en "
        "el documento de Nivel 2.",
        "",
    ]

    lines += ["## 10. Trazabilidad", ""]
    lines += [
        "Cada afirmación de este documento enlaza a `ruta#L inicio-L fin`. Los archivos fuente y su "
        "huella son:",
        "",
        _table(
            ["Archivo", "sha256"],
            [[f"`{path}`", f"`{digest}`"] for path, digest in sorted(sources.items())],
        ),
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- Nivel 4


def render_l4(
    project: str,
    facts: Sequence[Fact],
    sources: Mapping[str, str],
    meta: Mapping[str, str],
    diagrams: Sequence[object] = (),
) -> str:
    """README y onboarding: lo minimo para entender y arrancar, sin jerga innecesaria."""
    lines = _header(project, "README de onboarding (Nivel 4)", meta, facts)
    counts = _counts(facts)

    lines += ["## Qué es", ""]
    lines += [
        f"Proyecto **{project}** con {counts.get('module', 0)} módulos, "
        f"{counts.get('package', 0)} paquetes, "
        f"{counts.get('type', 0)} tipos y {counts.get('route', 0)} rutas HTTP documentadas.",
        "",
        _table(
            ["Módulo / paquete", "Cita"],
            [
                [f"`{fact.subject}`", _cite(fact.citation)]
                for fact in _by_kind(facts, "module") + _by_kind(facts, "package")
            ],
        ),
        "",
    ]

    lines += ["## Prerrequisitos", ""]
    # Solo la plataforma: propiedades declaradas y el parent del POM raiz. Los parents internos
    # de cada modulo son ruido para quien va a instalar el proyecto.
    root_parents = [fact for fact in _dedupe(_by_kind(facts, "parent")) if fact.citation.startswith("pom.xml")]
    prereq = _dedupe(_by_kind(facts, "property")) + root_parents
    lines += [
        _table(
            ["Requisito", "Versión", "Cita"],
            [[f"`{fact.subject}`", fact.detail, _cite(fact.citation)] for fact in prereq],
        ),
        "",
    ]

    lines += ["## Puesta en marcha", ""]
    plugins = [fact for fact in _by_kind(facts, "plugin") if "spring-boot" in fact.subject]
    rows: list[list[str]] = [
        ["Arranque local", "`mvn spring-boot:run`", _cite(fact.citation)] for fact in plugins
    ]
    # El comando de build se sostiene en el parent del POM raiz, no en una convencion.
    if root_parents:
        rows.append(["Compilar", "`mvn -DskipTests package`", _cite(root_parents[0].citation)])
    lines += [_table(["Objetivo", "Comando", "Cita"], rows), ""]

    lines += ["## Endpoints principales", ""]
    lines += [
        _table(
            ["Verbo", "Ruta", "Cita"],
            [
                [fact.attributes.get("verb", "—"), f"`{fact.attributes.get('path', '—')}`", _cite(fact.citation)]
                for fact in _by_kind(facts, "route")
            ],
        ),
        "",
    ]

    lines += ["## Fuentes", ""]
    lines += [
        f"Documento generado leyendo {len(sources)} archivos del repositorio. "
        "Las secciones sin evidencia se declaran como huecos, no se rellenan.",
        "",
    ]
    return "\n".join(lines)


#: Terminos que no pueden aparecer en la prosa del Nivel 3 (si pueden ir como codigo entre backticks).
JARGON = (
    "endpoint",
    "payload",
    "json",
    "jwt",
    "header",
    "request",
    "response",
    "query",
    "token",
    "api",
    "backend",
    "frontend",
    "middleware",
    "framework",
    "repositorio",
    "commit",
)

#: Traduccion de verbo HTTP a accion en lenguaje llano. Es una convencion documentada, no una
#: invencion semantica sobre el dominio del cliente.
VERB_LABELS = {
    "GET": "Consultar información",
    "POST": "Enviar datos",
    "PUT": "Actualizar un registro",
    "PATCH": "Modificar un registro",
    "DELETE": "Eliminar un registro",
    "ANY": "Operación disponible",
}


# --------------------------------------------------------------------------- Nivel 2


def render_l2(
    project: str,
    facts: Sequence[Fact],
    sources: Mapping[str, str],
    meta: Mapping[str, str],
    diagrams: Sequence[object] = (),
) -> str:
    """Operación y despliegue: entorno, puertos, artefactos, procedimientos y CI.

    Nunca incluye valores de variables de entorno: sólo nombres. Un documento que copia una clave
    es un incidente, no documentación.
    """
    lines = _header(project, "Operación y despliegue (Nivel 2)", meta, facts)
    counts = _counts(facts)

    lines += ["## 1. Entorno requerido", ""]
    env_rows = [
        [f"`{fact.subject}`", fact.detail, _cite(fact.citation)] for fact in _by_kind(facts, "env_var")
    ]
    if env_rows:
        lines += [
            "> Sólo se documentan los **nombres** de las variables. Los valores de los archivos de "
            "ejemplo no se copian, y un `.env` real nunca se lee.",
            "",
            _table(["Variable", "Archivo de ejemplo", "Cita"], env_rows),
            "",
        ]
    else:
        lines += [NO_EVIDENCE, ""]

    lines += ["## 2. Puertos y servicios", ""]
    port_rows = [
        [f"`{fact.subject}`", fact.detail, _cite(fact.citation)] for fact in _by_kind(facts, "port")
    ]
    service_rows = [
        [f"`{fact.subject}`", fact.detail, _cite(fact.citation)]
        for fact in _by_kind(facts, "service")
    ]
    if service_rows:
        lines += [_table(["Servicio", "Origen", "Cita"], service_rows), ""]
    if port_rows:
        lines += [_table(["Puerto", "Publicado por", "Cita"], port_rows), ""]
    if not service_rows and not port_rows:
        lines += [NO_EVIDENCE, ""]

    lines += ["## 3. Artefactos de infraestructura", ""]
    image_rows = [
        [f"`{fact.subject}`", fact.detail, _cite(fact.citation)] for fact in _by_kind(facts, "image")
    ]
    process_rows = [
        [f"`{fact.subject}`", fact.detail, _cite(fact.citation)]
        for fact in _by_kind(facts, "process")
    ]
    order_rows = [
        [f"`{fact.subject}`", _cite(fact.citation)] for fact in _by_kind(facts, "dependency_edge")
    ]
    if image_rows:
        lines += [_table(["Imagen base", "Rol", "Cita"], image_rows), ""]
    if process_rows:
        lines += [_table(["Arranque del contenedor", "Rol", "Cita"], process_rows), ""]
    if order_rows:
        lines += [_table(["Orden de arranque", "Cita"], order_rows), ""]
    if not image_rows and not process_rows and not order_rows:
        lines += [NO_EVIDENCE, ""]

    lines += ["## 4. Procedimientos", ""]
    command_rows = [
        [f"`{fact.subject}`", f"`{fact.detail}`", _cite(fact.citation)]
        for fact in _by_kind(facts, "command")
    ]
    if command_rows:
        lines += [_table(["Comando", "Qué ejecuta", "Cita"], command_rows), ""]
    else:
        lines += [NO_EVIDENCE, ""]

    lines += ["## 5. Integración continua", ""]
    workflow_rows = [
        [f"`{fact.subject}`", fact.detail, _cite(fact.citation)] for fact in _by_kind(facts, "workflow")
    ]
    trigger_rows = [
        [f"`{fact.subject}`", fact.detail, _cite(fact.citation)] for fact in _by_kind(facts, "trigger")
    ]
    job_rows = [
        [f"`{fact.subject}`", fact.detail, _cite(fact.citation)] for fact in _by_kind(facts, "ci_job")
    ]
    if workflow_rows:
        lines += [_table(["Workflow", "Archivo", "Cita"], workflow_rows), ""]
    if trigger_rows:
        lines += [_table(["Disparador", "Workflow", "Cita"], trigger_rows), ""]
    if job_rows:
        lines += [_table(["Job", "Workflow", "Cita"], job_rows), ""]
    if not workflow_rows and not job_rows:
        lines += [NO_EVIDENCE, ""]

    lines += ["## 6. Alcance y límites", ""]
    lines += [
        f"- Afirmaciones documentadas: **{len(facts)}** · entorno {counts.get('env_var', 0)}, "
        f"puertos {counts.get('port', 0)}, servicios {counts.get('service', 0)}, "
        f"comandos {counts.get('command', 0)}, jobs de CI {counts.get('ci_job', 0)}",
        "- **No** se documentan valores de secretos ni el contenido de un `.env` real.",
        "- **No** se describe infraestructura provisionada que no esté declarada en el repositorio: "
        "Terraform y CloudFormation aún no se leen.",
        "",
    ]
    return "\n".join(lines)


def render_l3(
    project: str,
    facts: Sequence[Fact],
    sources: Mapping[str, str],
    meta: Mapping[str, str],
    diagrams: Sequence[object] = (),
) -> str:
    """Guia de uso para personas sin perfil tecnico: acciones, ajustes y avisos."""
    lines = _header(project, "Guía de uso (Nivel 3)", meta, facts, plain=True)

    lines += ["## Qué puedes hacer", ""]
    rows = []
    for fact in _by_kind(facts, "route"):
        verb = fact.attributes.get("verb", "ANY").upper()
        route = fact.attributes.get("path", "/")
        rows.append([VERB_LABELS.get(verb, "Operación disponible"), f"`{route}`", _cite(fact.citation)])
    lines += [_table(["Acción", "Dirección", "Cita"], rows), ""]

    lines += ["## Valores que puedes ajustar", ""]
    settings = _by_kind(facts, "config_key")
    lines += [
        _table(
            ["Ajuste", "Valor actual", "Cita"],
            [[f"`{fact.attributes.get('key', fact.subject)}`", f"`{fact.detail}`", _cite(fact.citation)] for fact in settings],
        ),
        "",
    ]

    lines += ["## Preguntas frecuentes", ""]
    lines += [NO_EVIDENCE, ""]

    lines += ["## Aviso", ""]
    lines += [
        "Esta guía se construye a partir de lo que el sistema expone hoy y de su configuración actual. "
        "No sustituye la validación con el equipo responsable del negocio: si una acción no aparece "
        "aquí, es que no está declarada en el sistema, no que no exista.",
        "",
    ]
    return "\n".join(lines)


#: Renderizadores disponibles por nivel. Se declara al final: las funciones deben existir antes.
RENDERERS = {"l1": render_l1, "l2": render_l2, "l3": render_l3, "l4": render_l4}
