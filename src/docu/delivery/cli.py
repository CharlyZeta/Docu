"""Interfaz de linea de comandos (Plan.md §3).

Deliberadamente stdlib: el CLI actual no obliga a instalar nada, para que `docu --help`
funcione en cualquier maquina desde el primer minuto. Typer queda como extra `[cli]`.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from docu import __version__
from docu.core.contracts import SCHEMA_VERSION, GateOutcome, Mode
from docu.core.policy import Thresholds
from docu.core.profile import Profile
from docu.delivery.exit_codes import ExitCode

DEFAULT_PROFILE = "docu.profile.yaml"

_EPILOG = """\
Códigos de salida: 0 ok · 10 sin cambios · 20 revision · 30 presupuesto agotado
                  40 fuente no citable · 50 no implementado · 60 perfil inválido
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docu",
        description="Agente autónomo de documentación técnica: agnóstico, verificable e incremental.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--profile",
        default=None,
        help=f"ruta del perfil (default: {DEFAULT_PROFILE} en la raíz del proyecto)",
    )
    parser.add_argument("--version", action="version", version=f"docu {__version__} (schema {SCHEMA_VERSION})")

    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="detecta el stack y propone un perfil")
    p_init.add_argument("--root", default=".", help="raíz del proyecto a documentar")
    p_init.add_argument("--project", default=None, help="nombre del proyecto")
    p_init.add_argument("--force", action="store_true", help="regenera el perfil desde cero")
    p_init.add_argument("--apply", action="store_true", help="aplica la orden de cambio propuesta")
    p_init.add_argument("--dry-run", action="store_true", help="muestra el perfil sin escribirlo")

    p_index = sub.add_parser("index", help="ingesta incremental por content_hash")
    p_index.add_argument("--since", default=None, help="ref git desde la que indexar")

    p_gen = sub.add_parser("gen", help="genera y audita documentación")
    # `--profile` viaja también en el subcomando: exigir el orden global es fricción gratuita.
    p_gen.add_argument("--profile", default=argparse.SUPPRESS, help="perfil del proyecto")
    p_gen.add_argument("--level", choices=["l1", "l2", "l3", "l4"], action="append", default=None)
    p_gen.add_argument("--mode", choices=[m.value for m in Mode], default=None)
    p_gen.add_argument("--root", default=".", help="raíz del proyecto a documentar")
    p_gen.add_argument("--out", default=None, help="directorio de salida (default: el del perfil)")
    p_gen.add_argument("--project", default=None, help="nombre del proyecto en el documento")
    p_gen.add_argument(
        "--include-tests",
        action="store_true",
        help="incluye src/test (por defecto se excluye: no es API del producto)",
    )
    p_gen.add_argument(
        "--stamp",
        action="store_true",
        help="incluye la fecha de generación (rompe la idempotencia byte a byte; no usar en CI)",
    )
    p_gen.add_argument(
        "--incremental",
        action="store_true",
        help="regenera solo las páginas stale o expired (usa .docu/manifest.json)",
    )
    p_gen.add_argument("--manifest", default=None, help="ruta del manifest de frescura")
    p_gen.add_argument("--ttl-days", type=int, default=None, help="días antes de marcar expired")

    p_status = sub.add_parser("status", help="frescura, cobertura y huecos declarados")
    p_status.add_argument("--root", default=".")
    p_status.add_argument("--profile", default=argparse.SUPPRESS)
    p_status.add_argument("--manifest", default=None)
    p_status.add_argument("--json", action="store_true", help="salida legible por máquina")

    p_ci = sub.add_parser("ci", help="integraciones de CI (validar y proponer PR)")
    ci_sub = p_ci.add_subparsers(dest="ci_command", required=True)
    p_check = ci_sub.add_parser("check", help="valida frescura (falla rápido, sin LLM)")
    p_check.add_argument("--root", default=".")
    p_check.add_argument("--profile", default=argparse.SUPPRESS)
    p_check.add_argument("--manifest", default=None)
    p_check.add_argument("--json", action="store_true")
    p_regen = ci_sub.add_parser("regen", help="regenera lo stale y prepara el PR")
    p_regen.add_argument("--root", default=".")
    p_regen.add_argument("--profile", default=argparse.SUPPRESS)
    p_regen.add_argument("--out", default="docs/generated")
    p_regen.add_argument("--manifest", default=None)
    p_regen.add_argument("--project", default=None)
    p_regen.add_argument("--pr-body", default=None, help="ruta del cuerpo del PR a generar")

    p_drift = sub.add_parser("drift", help="conformidad prescriptivo vs. real")
    p_drift.add_argument("--root", default=".")
    p_drift.add_argument("--architecture", default=None, help="ruta del modelo arquitectónico")
    p_drift.add_argument("--include-tests", action="store_true")
    p_drift.add_argument("--json", action="store_true")
    p_drift.add_argument(
        "--bootstrap",
        action="store_true",
        help="escribe el modelo inicial desde el código actual (foto de partida)",
    )
    p_drift.add_argument("--out", default="architecture.yaml", help="ruta del modelo al bootstrappear")

    p_audit = sub.add_parser("audit", help="auditoría determinista (sin modelos)")
    p_audit.add_argument("--root", default=".")
    p_audit.add_argument("--profile", default=argparse.SUPPRESS)
    p_audit.add_argument("--out", default=None, help="directorio de la documentación generada")
    p_audit.add_argument("--min-score", type=float, default=0.0, help="falla si la nota es menor")
    p_audit.add_argument("--json", action="store_true")
    p_audit.add_argument("--report", default=None, help="escribe el informe Markdown")

    p_site = sub.add_parser("site", help="publica la documentación como web (divulgación progresiva)")
    p_site.add_argument("--root", default=".")
    p_site.add_argument("--profile", default=argparse.SUPPRESS)
    p_site.add_argument("--out", default=None, help="directorio de la web (por defecto <docs>/site)")
    p_site.add_argument(
        "--docs", default=None, help="directorio de la documentación generada (de ahí salen los diagramas)"
    )
    p_site.add_argument(
        "--level", action="append", dest="site_levels", default=None, help="nivel a publicar (repetible)"
    )

    p_learn = sub.add_parser("learn", help="revisa, promueve o federa artefactos aprendidos")
    p_learn.add_argument("--promote", action="store_true", help="promueve candidatos validados")
    p_learn.add_argument("--federate", action="store_true", help="envía huellas anonimizadas (opt-in)")
    p_learn.add_argument("--dry-run", action="store_true", help="muestra el payload sin enviarlo")
    p_learn.add_argument("--root", default=".")
    p_learn.add_argument("--ledger", default=None, help="ruta del ledger (por defecto .docu/ledger.jsonl)")
    p_learn.add_argument("--patterns", default=None, help="ruta de la biblioteca de patrones")
    p_learn.add_argument("--endpoint", default=None, help="endpoint de federación (http/https)")
    p_learn.add_argument("--json", action="store_true")

    p_serve = sub.add_parser("serve", help="servidor MCP de solo lectura")
    p_serve.add_argument("--mcp", action="store_true", help="transporte MCP (stdio por defecto)")
    p_serve.add_argument("--port", type=int, default=None, help="puerto para transporte HTTP")
    p_serve.add_argument("--root", default=".", help="raíz del proyecto documentado")
    p_serve.add_argument("--profile", default=argparse.SUPPRESS, help="perfil (aplica su glosario)")
    p_serve.add_argument("--out", default=None, help="directorio de la documentación generada")
    p_serve.add_argument(
        "--workspace",
        default=None,
        help="carpeta que contiene varios repositorios documentados (un servidor, varios proyectos)",
    )

    return parser


def _guard(profile_path: str | None) -> ExitCode | None:
    """Verificacion minima previa: si el usuario declaro un perfil, debe existir."""
    if not profile_path:
        return None
    if not Path(profile_path).exists():
        print(f"error: no existe el perfil {profile_path!r}; ejecuta `docu init`", file=sys.stderr)
        return ExitCode.CONFIG_ERROR
    return None


class CliError(RuntimeError):
    """Error de uso con codigo de salida propio: el CI decide sin parsear mensajes."""

    def __init__(self, message: str, code: ExitCode) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResolvedOptions:
    """Perfil + banderas de CLI ya resueltas: una sola verdad para generar y verificar."""

    profile: Profile | None
    project: str
    levels: tuple[str, ...]
    out_dir: Path
    ttl_days: int
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    thresholds: Thresholds
    manifest: Path | None


def _resolve(args: argparse.Namespace, root: Path) -> ResolvedOptions:
    """Combina perfil y banderas. La bandera explícita gana; el perfil rellena el resto."""
    from docu.core.profile import ProfileError, find, load

    explicit = Path(args.profile) if getattr(args, "profile", None) else None
    path = explicit if explicit is not None else find(root)
    try:
        profile = load(path, fallback_project=root.name) if path else None
    except ProfileError as error:
        raise CliError(f"perfil inválido: {error}", ExitCode.CONFIG_ERROR) from None

    cli_levels = tuple(getattr(args, "level", None) or ())
    levels = cli_levels or (profile.levels if profile else ("l1", "l4"))
    out = getattr(args, "out", None) or (profile.output_dir if profile else "docs/generated")
    ttl = getattr(args, "ttl_days", None) or (profile.ttl_days if profile else 90)
    manifest_flag = getattr(args, "manifest", None)
    return ResolvedOptions(
        profile=profile,
        project=getattr(args, "project", None) or (profile.project if profile else root.name),
        levels=levels,
        out_dir=Path(out) if Path(out).is_absolute() else root / out,
        ttl_days=int(ttl),
        include=profile.include if profile else (),
        exclude=profile.effective_exclude if profile else (),
        thresholds=profile.thresholds if profile else Thresholds(),
        manifest=Path(manifest_flag) if manifest_flag else None,
    )


def _force_utf8() -> None:
    """Consolas Windows heredadas usan cp1252: sin esto, los acentos salen rotos."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # pragma: no cover - streams ya cerrados
                pass


def main(argv: Sequence[str] | None = None) -> int:
    _force_utf8()
    args = _build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except CliError as error:
        print(f"error: {error}", file=sys.stderr)
        return int(error.code)


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "init":
        return _run_init(args)

    if args.command == "gen":
        return _run_generate(args)

    if args.command == "status":
        return _run_status(args, quiet_ok=False)

    if args.command == "ci":
        if args.ci_command == "check":
            return _run_status(args, quiet_ok=True)
        return _run_ci_regen(args)

    if args.command == "drift":
        return _run_drift(args)

    if args.command == "audit":
        return _run_audit(args)

    if args.command == "site":
        return _run_site(args)

    if args.command == "serve":
        return _run_serve(args)

    if args.command == "learn":
        return _run_learn(args)

    guarded = _guard(args.profile)
    if guarded is not None:
        return int(guarded)

    pending = {
        "index": "F1 · ingesta + índice",
    }[args.command]
    print(f"docu {args.command}: pendiente de {pending}")
    return int(ExitCode.NOT_IMPLEMENTED)


def _learn_settings(root: Path) -> tuple[float, float]:
    """Lee los umbrales de promoción del perfil; si no existen, usa los valores documentados."""
    from docu.core.yamlmini import YamlError, parse

    for name in ("docu.profile.yaml", "docu.profile.yml"):
        candidate = root / name
        if not candidate.exists():
            continue
        try:
            document = parse(candidate.read_text(encoding="utf-8"))
        except YamlError:
            break
        section = document.get("learn")
        if isinstance(section, dict):
            promote = float(section.get("promotion_delta") or 0.05)  # type: ignore[arg-type]
            rollback = float(section.get("rollback_drop") or 0.05)  # type: ignore[arg-type]
            return promote, rollback
    return 0.05, 0.05


def _run_learn(args: argparse.Namespace) -> int:
    """Revisa el ledger, promueve patrones validados o prepara el payload de federación."""
    import json as jsonlib

    from docu.learn import federation, ledger, patterns, promotion

    root = Path(args.root)
    ledger_path = ledger.ledger_file(root, args.ledger)
    patterns_path = Path(args.patterns) if args.patterns else root / patterns.PATTERNS_PATH
    records = ledger.load(ledger_path)
    library = patterns.PatternLibrary.load(patterns_path)
    summary = ledger.summarize(records)

    if args.federate:
        payload = federation.build_payload(library)
        if args.json or args.dry_run:
            print(federation.preview(payload))
        result = federation.send(payload, args.endpoint, dry_run=args.dry_run or not args.endpoint)
        if not args.json:
            print(
                f"federación: {'enviado' if result.get('sent') else 'no enviado'} · "
                f"{result.get('patterns', 0)} patrones · {result.get('reason', 'ok')}"
            )
        if not result.get("sent") and args.dry_run:
            return int(ExitCode.OK)
        return int(ExitCode.OK if result.get("sent") else ExitCode.CONFIG_ERROR)

    promote_delta, rollback_drop = _learn_settings(root)

    if args.promote:
        decisions = []
        changed = False
        for candidate in patterns.candidates_from(records):
            current = library.patterns.get(candidate.pattern.pattern_id)
            decision = promotion.decide(
                current,
                candidate.pattern,
                promotion_delta=promote_delta,
                rollback_drop=rollback_drop,
            )
            if decision.action == promotion.PROMOTE:
                library.promote(candidate.pattern)
                changed = True
            elif decision.action == promotion.ROLLBACK:
                if library.revert(candidate.pattern.pattern_id):
                    changed = True
            decisions.append(decision)

        if changed:
            library.save(patterns_path)

        if args.json:
            print(
                jsonlib.dumps(
                    {
                        "decisions": [
                            {
                                "action": decision.action,
                                "pattern_id": decision.pattern_id,
                                "delta": decision.delta,
                                "reasons": list(decision.reasons),
                            }
                            for decision in decisions
                        ],
                        "version": library.version,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            if not decisions:
                print("sin candidatos: el ledger no tiene corridas suficientes")
            for decision in decisions:
                print(f"  {decision.describe()}")
            print(f"biblioteca de patrones: v{library.version} · {len(library.patterns)} patrones")
        return int(ExitCode.OK if changed else ExitCode.NO_CHANGES)

    if args.json:
        print(jsonlib.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"ledger: {summary['runs']} corridas · proyectos: {', '.join(summary['projects']) or '—'}"
        )
        metrics = summary["metrics"] or {}
        if metrics:
            print(
                "  medias: "
                + " · ".join(f"{name} {value:.2f}" for name, value in metrics.items())
            )
        print(f"  compuerta: {ledger.outcome_counts(records)} · biblioteca v{library.version}")
        for candidate in patterns.candidates_from(records):
            print(f"  candidato: {candidate.pattern.pattern_id} ({'; '.join(candidate.reasons)})")
    return int(ExitCode.OK if records else ExitCode.NO_CHANGES)


def _run_audit(args: argparse.Namespace) -> int:
    """Auditoría determinista: cinco comprobaciones, cero modelos, cero red."""
    import json as jsonlib

    from docu.audit.verify import audit

    root = Path(args.root).resolve()
    options = _resolve(args, root)
    report = audit(
        root,
        docs_dir=args.out or options.out_dir,
        levels=options.levels,
        profile_path=str(options.profile.path) if options.profile and options.profile.path else None,
    )

    if args.report:
        destination = Path(args.report)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(report.to_markdown(), encoding="utf-8")

    if args.json:
        print(jsonlib.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(report.to_markdown())

    if report.score < args.min_score:
        print(
            f"auditoría por debajo del mínimo: {report.score:.1f} < {args.min_score:.1f}",
            file=sys.stderr,
        )
        return int(ExitCode.NEEDS_REVIEW)
    return int(ExitCode.OK if report.passed else ExitCode.NEEDS_REVIEW)


def _run_site(args: argparse.Namespace) -> int:
    """Publica la web: lo esencial visible y la prueba a un clic."""
    from docu.core.contracts import sha256_of
    from docu.generate.facts import unsupported
    from docu.generate.pipeline import collect_facts
    from docu.publish.site import build_site

    root = Path(args.root).resolve()
    options = _resolve(args, root)
    levels = tuple(args.site_levels or options.levels)
    facts, sources = collect_facts(
        root, include=options.include, exclude=options.exclude, include_tests=getattr(args, "include_tests", False)
    )
    if not facts:
        print("error: no se detectó nada documentable", file=sys.stderr)
        return int(ExitCode.UNCITABLE_SOURCE)

    digest = sha256_of("|".join(f"{path}:{sha}" for path, sha in sorted(sources.items())))[:12]
    # `--out` es la web; la documentación generada (y sus diagramas) se resuelve aparte: mezclarlas
    # hacía que la web buscara los diagramas dentro de su propia carpeta de salida.
    docs_dir = Path(args.docs) if getattr(args, "docs", None) else (
        Path(options.profile.output_dir) if options.profile else Path("docs") / "generated"
    )
    out_dir = Path(args.out) if args.out else docs_dir / "site"
    project = options.project or root.name
    pages = build_site(
        root,
        out_dir,
        project,
        facts,
        meta={
            "version": __version__,
            "digest": digest,
            "facts": str(len(facts)),
            "unsupported": str(len(unsupported(facts))),
        },
        levels=levels,
        diagrams_dir=docs_dir / "diagrams",
    )
    print(f"{project}: {len(facts)} afirmaciones · {len(pages)} páginas · web en {out_dir}")
    for page in pages:
        print(f"  {page.name}")
    return int(ExitCode.OK)


def _run_serve(args: argparse.Namespace) -> int:
    """Sirve la documentación por MCP: stdio (por defecto) o puente HTTP con `--port`."""
    from docu.delivery.mcp_server import build_server

    if not args.mcp:
        print(
            "error: el servidor solo habla MCP (`docu serve --mcp`); "
            "sin --port usa stdio, con --port usa el puente HTTP",
            file=sys.stderr,
        )
        return int(ExitCode.CONFIG_ERROR)

    server = build_server(
        args.root,
        args.out,
        workspace=args.workspace,
        profile_path=getattr(args, "profile", None),
    )
    if args.workspace:
        projects = server.projects()
        documented = ", ".join(ref.name for ref in projects) or "ninguno"
        print(f"workspace: {len(projects)} proyectos · {documented}", file=sys.stderr)

    if args.port:
        from docu.delivery.http_server import serve_http

        serve_http(server, port=args.port)
        return int(ExitCode.OK)
    return server.serve()


def _run_drift(args: argparse.Namespace) -> int:
    """Compara arquitectura declarada y código real. Bootstrap incluido para empezar de cero."""
    import json as jsonlib

    from docu.conformance.drift import analyze, bootstrap
    from docu.conformance.model import to_yaml

    root = Path(args.root)

    if args.bootstrap:
        model = bootstrap(root, include_tests=args.include_tests)
        if model.is_empty:
            print("error: no se detectaron componentes ni rutas para bootstrappear", file=sys.stderr)
            return int(ExitCode.CONFIG_ERROR)
        destination = Path(args.out) if Path(args.out).is_absolute() else root / args.out
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(to_yaml(model, root.name), encoding="utf-8")
        print(
            f"modelo inicial escrito en {destination} · "
            f"{len(model.components)} componentes · revisa y corrige antes de confiar en él"
        )
        return int(ExitCode.OK)

    report = analyze(root, args.architecture, include_tests=args.include_tests)
    if report.model.is_empty:
        print(
            "error: no hay modelo arquitectónico. Crea architecture.yaml u openapi.yaml, "
            "o genera una foto inicial con `docu drift --bootstrap`",
            file=sys.stderr,
        )
        return int(ExitCode.CONFIG_ERROR)

    if args.json:
        print(jsonlib.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(report.to_markdown())
    if report.is_clean:
        return int(ExitCode.OK)
    if not args.json:
        print(
            f"deriva detectada: {len(report.errors)} errores, {len(report.warnings)} avisos",
            file=sys.stderr,
        )
    return int(ExitCode.NEEDS_REVIEW)


def _run_init(args: argparse.Namespace) -> int:
    """Detecta el stack y propone el perfil. Si ya existe, produce una **orden de cambio**.

    Reejecutar `init` no es destructivo por defecto: la detección puede añadir estructura
    (niveles nuevos, exclusiones nuevas, glosario semilla) pero nunca reescribe umbrales, modo, TTL
    ni el vocabulario que escribió una persona.
    """
    from docu.core.profile import (
        ProfileError,
        candidate_paths,
        find,
        load,
        merge,
        plan_changes,
        render_change_order,
        to_yaml,
    )
    from docu.delivery.proposal import propose

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"error: no existe la raíz {root}", file=sys.stderr)
        return int(ExitCode.CONFIG_ERROR)

    try:
        proposed = propose(root, project=args.project)
    except ProfileError as error:
        print(f"error: {error}", file=sys.stderr)
        return int(ExitCode.CONFIG_ERROR)

    existing_path = find(root)

    # Caso 1: no hay perfil (o se pidió regenerar desde cero).
    if existing_path is None or args.force:
        rendered = to_yaml(proposed)
        destination = existing_path or candidate_paths(root)[0]
        print(f"proyecto: {proposed.project}")
        print(f"  niveles propuestos: {', '.join(proposed.levels)}")
        print(f"  exclusiones por defecto: {len(proposed.exclude)} patrones")
        if proposed.glossary:
            print(f"  glosario semilla: {len(proposed.glossary)} frases")
        else:
            print("  glosario semilla: vacío (añádelo si el dominio tiene jerga propia)")
        if args.dry_run:
            print()
            print(rendered)
            return int(ExitCode.OK)
        destination.write_text(rendered, encoding="utf-8")
        print(f"  escrito: {destination}")
        print()
        print("Siguiente paso: revisa exclusiones y umbrales, y ejecuta `docu gen`.")
        return int(ExitCode.OK)

    # Caso 2: ya existe perfil → orden de cambio.
    existing = load(existing_path)
    if existing is None:  # pragma: no cover - find() ya garantizó existencia
        print(f"error: no se pudo leer {existing_path}", file=sys.stderr)
        return int(ExitCode.CONFIG_ERROR)

    changes = plan_changes(existing, proposed)
    applied = [change for change in changes if change.applied]

    if args.dry_run:
        print(render_change_order(changes, existing.project))
        return int(ExitCode.OK)

    if not applied:
        kept = len(changes)
        if kept:
            suffix = f" ({kept} decisión humana conservada)" if kept == 1 else f" ({kept} decisiones humanas conservadas)"
        else:
            suffix = ""
        print(f"sin cambios en el perfil{suffix}")
        return int(ExitCode.NO_CHANGES)

    report = Path(root) / ".docu" / "init-change-order.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_change_order(changes, existing.project), encoding="utf-8")

    if not args.apply:
        print(f"orden de cambio propuesta para {existing.project}:")
        for index, change in enumerate(applied, start=1):
            print(f"  {index}. {change.describe()}")
        for change in changes:
            if not change.applied:
                print(f"  · conservado: {change.field} — {change.reason}")
        print()
        print(f"informe: {report}")
        print("no se escribió nada. Aplica con `docu init --apply`.")
        return int(ExitCode.NEEDS_REVIEW)

    merged = merge(existing, proposed)
    existing_path.write_text(to_yaml(merged), encoding="utf-8")
    print(f"orden de cambio aplicada sobre {existing_path}:")
    for index, change in enumerate(applied, start=1):
        print(f"  {index}. {change.describe()}")
    for change in changes:
        if not change.applied:
            print(f"  · conservado: {change.field} — {change.reason}")
    print(f"informe: {report}")
    return int(ExitCode.OK)


def _run_generate(args: argparse.Namespace) -> int:
    """Genera documentación obedeciendo el perfil, y traduce la compuerta a código de salida."""
    from docu.generate.pipeline import generate

    root = Path(args.root).resolve()
    options = _resolve(args, root)
    unsupported_levels = [level for level in options.levels if level not in ("l1", "l2", "l3", "l4")]
    if unsupported_levels:
        print(
            f"error: niveles disponibles hoy: l1, l2, l3, l4 (pedidos: {', '.join(unsupported_levels)})",
            file=sys.stderr,
        )
        return int(ExitCode.CONFIG_ERROR)

    result = generate(
        root,
        options.out_dir,
        levels=options.levels,
        project=options.project,
        include_tests=args.include_tests,
        stamp=args.stamp,
        incremental=args.incremental,
        manifest_path=options.manifest,
        ttl_days=options.ttl_days,
        include=options.include,
        exclude=options.exclude,
        thresholds=options.thresholds,
    )
    states = ", ".join(f"{level}={state.value}" for level, state in result.states.items())
    origin = f"perfil {options.profile.path.name}" if options.profile and options.profile.path else "sin perfil (detección automática)"
    print(
        f"{result.project}: {len(result.facts)} afirmaciones · "
        f"sin cita: {len(result.unsupported)} · "
        f"completitud {result.metrics.completeness:.1f}/10 · "
        f"concisión {result.metrics.conciseness:.1f}/10 · {result.elapsed_s:.2f}s · {origin}"
    )
    if states:
        print(f"  frescura: {states}")
    if result.unsupported_languages:
        detected = ", ".join(
            f"{name} ({count})" for name, count in result.unsupported_languages.items()
        )
        print(
            f"  aviso: lenguajes no soportados, no documentados: {detected}",
            file=sys.stderr,
        )
    for doc in result.docs:
        print(f"  escrito: {doc.path}")
    if args.incremental and not result.docs:
        print("sin cambios: todas las páginas están frescas")
        return int(ExitCode.NO_CHANGES)
    if result.gate.outcome is not GateOutcome.PUBLISH:
        print(f"compuerta: {result.gate.describe()}", file=sys.stderr)
        for reason in result.gate.reasons:
            print(f"  - {reason}", file=sys.stderr)
        return int(ExitCode.NEEDS_REVIEW)
    return int(ExitCode.OK)


def _run_status(args: argparse.Namespace, quiet_ok: bool) -> int:
    """Valida frescura. No genera nada: es la comprobación rápida de cada PR."""
    import json as jsonlib

    from docu.core.contracts import DocState
    from docu.generate.pipeline import inspect

    root = Path(args.root).resolve()
    options = _resolve(args, root)
    manifest, states, hashes = inspect(
        root,
        levels=options.levels,
        manifest_path=options.manifest,
        ttl_days=options.ttl_days,
        include=options.include,
        exclude=options.exclude,
    )
    from docu.generate.pipeline import manifest_file

    resolved_manifest = manifest_file(root, options.manifest)
    payload = {
        "project": manifest.project if manifest else None,
        "manifest": str(resolved_manifest),
        "generated": manifest is not None,
        "profile": str(options.profile.path) if options.profile and options.profile.path else None,
        "states": {level: state.value for level, state in states.items()},
        "hashes": hashes,
    }

    if getattr(args, "json", False):
        print(jsonlib.dumps(payload, ensure_ascii=False, indent=2))
        all_fresh = manifest is not None and all(state is DocState.FRESH for state in states.values())
        return int(ExitCode.OK if all_fresh else ExitCode.NEEDS_REVIEW)

    origin = "manifest encontrado" if manifest else "sin manifest: nada generado todavía"
    print(f"proyecto: {manifest.project if manifest else Path(args.root).name} ({origin})")
    for level, state in states.items():
        marker = {"fresh": "✔", "stale": "✖", "expired": "⏰"}.get(state.value, "?")
        print(f"  {marker} {level}: {state.value}  ({hashes[level][:19]}…)")

    all_fresh = manifest is not None and all(state is DocState.FRESH for state in states.values())
    if all_fresh:
        if not quiet_ok:
            print("todo fresco: no hay nada que regenerar")
        return int(ExitCode.OK)
    if not quiet_ok:
        print(
            "hay páginas desactualizadas: ejecuta `docu gen --incremental` o `docu ci regen`",
            file=sys.stderr,
        )
    return int(ExitCode.NEEDS_REVIEW)


def _run_ci_regen(args: argparse.Namespace) -> int:
    """Regenera lo stale y deja el cuerpo del PR listo para la acción de CI."""
    from docu.generate.pipeline import generate

    root = Path(args.root).resolve()
    options = _resolve(args, root)
    result = generate(
        root,
        options.out_dir,
        levels=options.levels,
        project=options.project,
        incremental=True,
        manifest_path=options.manifest,
        ttl_days=options.ttl_days,
        include=options.include,
        exclude=options.exclude,
        thresholds=options.thresholds,
    )
    body_path = Path(args.pr_body) if args.pr_body else root / ".docu" / "pr-body.md"
    root_path = root

    def _relative(path: Path) -> str:
        try:
            return path.resolve().relative_to(root_path).as_posix()
        except ValueError:
            return str(path)

    lines = [
        "## Documentación regenerada por `docu`",
        "",
        f"- Proyecto: `{result.project}`",
        f"- Afirmaciones: {len(result.facts)} · sin cita: {len(result.unsupported)}",
        f"- Completitud: {result.metrics.completeness:.1f}/10 · concisión: {result.metrics.conciseness:.1f}/10",
        f"- Compuerta: `{result.gate.outcome.value}`",
        "",
        "| Nivel | Estado detectado |",
        "|---|---|",
    ]
    lines += [f"| {level} | {state.value} |" for level, state in result.states.items()]
    if result.docs:
        lines += ["", "Archivos actualizados:", ""]
        lines += [f"- `{_relative(doc.path)}`" for doc in result.docs]
    else:
        lines += ["", "_Sin cambios: todas las páginas ya estaban frescas._"]
    body_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"{result.project}: {len(result.docs)} páginas regeneradas · PR body: {body_path}")
    if result.gate.outcome is not GateOutcome.PUBLISH:
        print(f"compuerta: {result.gate.describe()}", file=sys.stderr)
        return int(ExitCode.NEEDS_REVIEW)
    return int(ExitCode.OK)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
