"""Comparador de arquitectura prescriptiva contra el codigo real.

Cuatro clases de discrepancia, y ninguna se "arregla" sola: la deriva arquitectonica puede ser
intencionada (el modelo esta viejo) o accidental (la implementacion se desvio). El agente propone
la accion mas probable y deja el registro; decidir es del humano.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from docu.adapters.langs.registry import adapter_for
from docu.conformance.model import ArchitectureModel, DeclaredComponent, Route, load_architecture
from docu.generate.pipeline import collect_facts, _discover, _read

SEVERITY = {
    "undeclared_route": "warning",
    "missing_implementation": "error",
    "missing_component": "error",
    "undeclared_dependency": "warning",
    "missing_dependency": "warning",
}

ACTION = {
    "undeclared_route": "declarar la ruta en el modelo o retirarla del codigo",
    "missing_implementation": "implementar la ruta declarada o corregir el contrato",
    "missing_component": "crear el componente declarado o retirarlo del modelo",
    "undeclared_dependency": "declarar la dependencia (cambio intencionado) o abrir deuda tecnica",
    "missing_dependency": "verificar el cableado o actualizar el modelo",
}


@dataclass(frozen=True, slots=True)
class Discrepancy:
    kind: str
    subject: str
    detail: str
    code_citation: str | None = None
    declaration_source: str | None = None

    @property
    def severity(self) -> str:
        return SEVERITY.get(self.kind, "warning")

    @property
    def action(self) -> str:
        return ACTION.get(self.kind, "revisar")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "subject": self.subject,
            "detail": self.detail,
            "code_citation": self.code_citation,
            "declaration_source": self.declaration_source,
            "action": self.action,
        }


@dataclass(slots=True)
class DriftReport:
    model: ArchitectureModel
    discrepancies: list[Discrepancy] = field(default_factory=list)
    routes_in_code: int = 0
    components_in_code: int = 0

    @property
    def errors(self) -> list[Discrepancy]:
        return [item for item in self.discrepancies if item.severity == "error"]

    @property
    def warnings(self) -> list[Discrepancy]:
        return [item for item in self.discrepancies if item.severity != "error"]

    @property
    def is_clean(self) -> bool:
        return not self.discrepancies

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "sources": list(self.model.sources),
            "routes_in_code": self.routes_in_code,
            "components_in_code": self.components_in_code,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "discrepancies": [item.to_dict() for item in self.discrepancies],
        }

    def to_markdown(self) -> str:
        lines = [
            "# Deriva arquitectónica",
            "",
            f"Modelo declarado: {', '.join(self.model.sources) or '—'} · "
            f"rutas en código: {self.routes_in_code} · componentes en código: {self.components_in_code}",
            "",
        ]
        if self.is_clean:
            lines.append("Sin discrepancias: el código implementa lo declarado.")
            return "\n".join(lines) + "\n"
        lines += ["| Tipo | Gravedad | Sujeto | Evidencia en código | Acción propuesta |", "|---|---|---|---|---|"]
        for item in self.discrepancies:
            lines.append(
                f"| `{item.kind}` | {item.severity} | `{item.subject}` | "
                f"{item.code_citation or '—'} | {item.action} |"
            )
        return "\n".join(lines) + "\n"

    def save(self, path: Path | str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target


# --------------------------------------------------------------------------- descriptivo


@dataclass(frozen=True, slots=True)
class RouteFact:
    """Ruta encontrada en el codigo, con su cita y el simbolo que la implementa."""

    key: str
    citation: str
    handler: str


@dataclass(frozen=True, slots=True)
class CodeFacts:
    routes: tuple[RouteFact, ...]
    components: Mapping[str, str]  # nombre de tipo -> cita
    dependencies: tuple[tuple[str, str], ...]  # (llamador, llamado)


def describe_code(root: Path | str, include_tests: bool = False) -> CodeFacts:
    """Lo que el codigo dice de si mismo: rutas, componentes y dependencias.

    Las dependencias se derivan de **imports** ademas de llamadas: un import es una relacion
    estatica y verificable entre archivos, mientras que el grafo de llamadas se queda corto en
    cuanto hay despacho dinamico. Ambas fuentes se unen, sin inventar aristas.
    """
    root_path = Path(root)
    facts, _sources = collect_facts(root_path, include_tests=include_tests)
    routes = tuple(
        RouteFact(key=fact.subject, citation=fact.citation, handler=fact.detail)
        for fact in facts
        if fact.kind == "route"
    )
    components = {fact.subject: fact.citation for fact in facts if fact.kind == "type"}
    owner_by_file = {
        citation.split("#")[0]: name for name, citation in components.items() if "#" in citation
    }

    edges: list[tuple[str, str]] = []
    for rel, path in _discover(root_path, include_tests=include_tests).items():
        adapter = adapter_for(rel)
        if adapter is None:
            continue
        source = _read(path)
        for caller, callee in adapter.calls(rel, source):  # type: ignore[attr-defined]
            edges.append((caller, callee))
        owner = owner_by_file.get(rel)
        if owner is None:
            continue
        for module in adapter.imports(rel, source):  # type: ignore[attr-defined]
            candidate = re.split(r"[./]", module)[-1]
            if candidate in components and candidate != owner:
                edges.append((owner, candidate))
    return CodeFacts(routes=routes, components=components, dependencies=tuple(dict.fromkeys(edges)))


# --------------------------------------------------------------------------- comparacion


def _short(name: str) -> str:
    """Ultimo segmento de un nombre calificado (`A.B.c` → `c`)."""
    return name.rsplit(".", 1)[-1]


def _owner(qualname: str) -> str:
    """Componente propietario de un simbolo: el **primer** segmento (`A.B.c` → `A`).

    Confundir esto con `_short` hacia que un metodo (`refreshtoken`) se tratara como componente
    y que las rutas no se atribuyeran a su controlador.
    """
    return qualname.split(".", 1)[0]


def compare(model: ArchitectureModel, code: CodeFacts) -> DriftReport:
    """Diferencias en ambos sentidos: lo declarado que no existe y lo que existe sin declarar."""
    report = DriftReport(model=model)
    report.routes_in_code = len(code.routes)
    report.components_in_code = len(code.components)

    declared_routes = model.declared_routes
    code_routes = {route.key: route for route in code.routes}
    for key, route in code_routes.items():
        if key not in declared_routes:
            report.discrepancies.append(
                Discrepancy(
                    kind="undeclared_route",
                    subject=key,
                    detail="la ruta existe en el código y no está declarada",
                    code_citation=route.citation,
                    declaration_source=",".join(model.sources) or None,
                )
            )
    for key in sorted(declared_routes - set(code_routes)):
        report.discrepancies.append(
            Discrepancy(
                kind="missing_implementation",
                subject=key,
                detail="la ruta está declarada y no existe en el código",
                declaration_source=",".join(model.sources) or None,
            )
        )

    declared_components = model.component_names
    for name in sorted(declared_components):
        if name not in code.components:
            report.discrepancies.append(
                Discrepancy(
                    kind="missing_component",
                    subject=name,
                    detail="componente declarado sin implementación detectable",
                    declaration_source=",".join(model.sources) or None,
                )
            )

    # Solo se comparan aristas atribuibles a componentes conocidos y **no reflexivas**: una clase
    # que se llama a si misma no es una dependencia arquitectonica.
    known = set(code.components)
    code_edges = {
        (_owner(caller), _owner(callee))
        for caller, callee in code.dependencies
        if _owner(caller) in known and _owner(callee) in known and _owner(caller) != _owner(callee)
    }
    for component in model.components:
        for dependency in component.depends_on:
            if (_owner(component.name), _owner(dependency)) not in code_edges:
                report.discrepancies.append(
                    Discrepancy(
                        kind="missing_dependency",
                        subject=f"{component.name} → {dependency}",
                        detail="dependencia declarada sin evidencia de llamada",
                        declaration_source=component.source or None,
                    )
                )

    declared_edges = {(_owner(left), _owner(right)) for left, right in model.declared_dependencies()}
    for caller, callee in sorted(code_edges):
        if caller in declared_components or callee in declared_components:
            if (caller, callee) not in declared_edges and (callee, caller) not in declared_edges:
                report.discrepancies.append(
                    Discrepancy(
                        kind="undeclared_dependency",
                        subject=f"{caller} → {callee}",
                        detail="dependencia detectada en el código y no declarada",
                        code_citation=code.components.get(callee),
                    )
                )
    return report


def analyze(
    root: Path | str,
    architecture: Path | str | None = None,
    include_tests: bool = False,
) -> DriftReport:
    model = load_architecture(Path(root), architecture)
    code = describe_code(root, include_tests=include_tests)
    return compare(model, code)


def bootstrap(root: Path | str, include_tests: bool = False) -> ArchitectureModel:
    """Genera el modelo inicial desde el codigo actual.

    No es prescriptivo todavia: es una **foto** que convierte cualquier cambio futuro en deriva
    visible. Revisar y corregir el archivo es el primer acto arquitectonico.
    """
    code = describe_code(root, include_tests=include_tests)
    components: dict[str, DeclaredComponent] = {}

    for name in sorted(code.components):
        dependencies = sorted(
            {
                _owner(callee)
                for caller, callee in code.dependencies
                if _owner(caller) == name and _owner(callee) in code.components and _owner(callee) != name
            }
        )
        components[name] = DeclaredComponent(
            name=name,
            kind="component",
            depends_on=tuple(dependencies),
        )

    for route in code.routes:
        _verb, _, path = route.key.partition(" ")
        owner = _owner(route.handler) if route.handler else path
        if owner not in components:
            components[owner] = DeclaredComponent(name=owner, kind="endpoint")
        component = components[owner]
        components[owner] = DeclaredComponent(
            name=component.name,
            kind=component.kind,
            provides=(*component.provides, Route(verb=_verb, path=path)),
            depends_on=component.depends_on,
            source=component.source,
        )

    return ArchitectureModel(components=tuple(components.values()), routes=())


__all__ = [
    "CodeFacts",
    "Discrepancy",
    "DriftReport",
    "analyze",
    "bootstrap",
    "compare",
    "describe_code",
]
