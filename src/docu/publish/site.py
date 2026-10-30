"""Publicación web de la documentación: lo esencial visible y la prueba a un clic.

La idea no es «más texto»: es **control del contenido con profundidad bajo demanda**. Cada
afirmación se muestra en tres escalones y el lector decide hasta dónde baja:

1. **Resumen** — la fila: qué es y de qué tipo.
2. **Detalle** — firma, anotaciones y valor declarado.
3. **Prueba** — la cita y el fragmento real del archivo, con números de línea.

Sin dependencias, sin CDN y sin JavaScript obligatorio: si el JS no corre, los tres escalones siguen
funcionando porque el tercero es un `<details>` nativo. El JS sólo añade buscar y expandir todo.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from docu.generate.facts import Fact

#: Máximo de líneas que se muestran en el panel de prueba.
SNIPPET_LINES = 40

#: Orden de las secciones de la web (etiqueta visible, tipos de hecho).
SECTIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("arquitectura", "Arquitectura", ("module", "package", "parent")),
    ("dependencias", "Dependencias", ("dependency", "property")),
    ("api", "API HTTP", ("route",)),
    ("configuracion", "Configuración", ("config_key",)),
    ("datos", "Modelo de datos", ("field",)),
    ("tipos", "Tipos", ("type",)),
    ("metodos", "Métodos", ("method",)),
    ("operacion", "Operación", ("env_var", "service", "port", "image", "process", "command",
                                "workflow", "trigger", "ci_job", "dependency_edge")),
)

#: Qué secciones publica cada nivel: la web no repite todo en todas las páginas.
LEVEL_SECTIONS: Mapping[str, tuple[str, ...]] = {
    "l1": ("arquitectura", "dependencias", "api", "configuracion", "datos", "tipos", "metodos"),
    "l2": ("operacion",),
    "l3": ("api",),
    "l4": ("arquitectura", "dependencias", "api"),
}

CSS = """
:root { --bg:#0f1115; --fg:#e6e8ec; --dim:#9aa3b2; --line:#242a35; --accent:#6ea8fe; --ok:#3fb950; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
header { position:sticky; top:0; backdrop-filter:blur(8px); background:#0f1115e6;
  border-bottom:1px solid var(--line); padding:.75rem 1.25rem; z-index:10; }
header .row { display:flex; gap:1rem; align-items:center; flex-wrap:wrap; max-width:1100px; margin:0 auto; }
header h1 { font-size:1rem; margin:0; font-weight:600; }
nav a { color:var(--dim); font-size:.9rem; }
nav a:hover { color:var(--fg); }
main { max-width:1100px; margin:0 auto; padding:1.5rem 1.25rem 4rem; }
h2 { margin:2.5rem 0 .75rem; font-size:1.15rem; border-bottom:1px solid var(--line); padding-bottom:.4rem; }
h3 { font-size:1rem; margin:1.5rem 0 .5rem; color:var(--dim); font-weight:600; }
p.lead { color:var(--dim); }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:.75rem; margin:1rem 0; }
.card { border:1px solid var(--line); border-radius:10px; padding:.9rem 1rem; background:#151922; }
.card .n { font-size:1.6rem; font-weight:700; }
.card .l { color:var(--dim); font-size:.85rem; }
table { width:100%; border-collapse:collapse; font-size:.92rem; }
th, td { text-align:left; padding:.45rem .6rem; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--dim); font-weight:600; font-size:.82rem; text-transform:uppercase; letter-spacing:.03em; }
code, pre { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:.86rem; }
code { background:#1b2029; padding:.1rem .35rem; border-radius:4px; }
pre { background:#12161d; border:1px solid var(--line); border-radius:8px; padding:.75rem;
  overflow:auto; max-height:22rem; }
pre .ln { color:#5a6472; user-select:none; display:inline-block; width:3.2rem; text-align:right; margin-right:.8rem; }
details { margin:.25rem 0 0; }
details > summary { cursor:pointer; color:var(--accent); font-size:.85rem; }
details[open] > summary { margin-bottom:.4rem; }
.cite { color:var(--dim); font-size:.82rem; }
.badge { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:.05rem .5rem;
  font-size:.75rem; color:var(--dim); }
.empty { color:var(--dim); border-left:3px solid #b08900; padding:.4rem .8rem; background:#1a1710; }
footer { color:var(--dim); font-size:.82rem; border-top:1px solid var(--line); margin-top:3rem; padding-top:1rem; }
input[type=search] { background:#151922; border:1px solid var(--line); color:var(--fg);
  border-radius:8px; padding:.45rem .7rem; min-width:16rem; }
button { background:#1b2029; color:var(--fg); border:1px solid var(--line); border-radius:8px;
  padding:.45rem .7rem; cursor:pointer; }
button:hover { border-color:var(--accent); }
.hidden { display:none !important; }
@media print { header, nav, button, input { display:none; } body { background:#fff; color:#000; } }
"""

JS = """
const q = document.querySelector('#q');
const rows = () => Array.from(document.querySelectorAll('tbody tr[data-search]'));
if (q) {
  q.addEventListener('input', () => {
    const needle = q.value.trim().toLowerCase();
    for (const row of rows()) {
      row.classList.toggle('hidden', needle !== '' && !row.dataset.search.includes(needle));
    }
    for (const section of document.querySelectorAll('section')) {
      const visible = Array.from(section.querySelectorAll('tbody tr[data-search]'))
        .some((row) => !row.classList.contains('hidden'));
      section.classList.toggle('hidden', !visible);
    }
  });
}
const all = document.querySelector('#expand');
if (all) {
  let open = false;
  all.addEventListener('click', () => {
    open = !open;
    for (const d of document.querySelectorAll('details')) d.open = open;
    all.textContent = open ? 'Contraer todo' : 'Expandir todo';
  });
}
"""


@dataclass(frozen=True, slots=True)
class Page:
    name: str
    title: str
    html: str


def escape(text: str) -> str:
    return html.escape(text, quote=True)


def snippet(root: Path, citation: str, limit: int = SNIPPET_LINES) -> str:
    """Fragmento real del archivo citado, con números de línea.

    Es la diferencia entre «confía en mí» y «compruébalo»: el tercer escalón de la web no es una
    descripción de la evidencia, es la evidencia.
    """
    path, _, span = citation.partition("#L")
    if not span:
        return ""
    target = root / path
    if not target.is_file():
        return ""
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    start_text, _, end_text = span.partition("-L")
    try:
        start = max(1, int(start_text))
        end = min(len(lines), int(end_text or start_text))
    except ValueError:
        return ""
    end = min(end, start + limit - 1)
    rendered: list[str] = []
    for number in range(start, end + 1):
        rendered.append(
            f'<span class="ln">{number}</span>{escape(lines[number - 1])}'
        )
    return "\n".join(rendered)


def _cell(text: str) -> str:
    return f"<code>{escape(text)}</code>" if text else "—"


def _row(fact: Fact, root: Path) -> str:
    """Una fila: resumen visible + detalle + prueba, en un solo `<details>` anidado."""
    searchable = " ".join(
        [fact.kind, fact.subject, fact.detail, fact.citation, *map(str, fact.attributes.values())]
    ).lower()
    annotations = fact.attributes.get("annotations", "")
    extra = ""
    if annotations and annotations != "—":
        extra = f'<div class="cite">Anotaciones: {_cell(annotations)}</div>'
    code = snippet(root, fact.citation)
    proof = (
        f"<pre>{code}</pre>" if code else '<div class="empty">Sin fragmento disponible.</div>'
    )
    return (
        f'<tr data-search="{escape(searchable)}">'
        f"<td><code>{escape(fact.subject)}</code></td>"
        f"<td>{_cell(fact.detail)}</td>"
        f"<td><details><summary>Ver prueba</summary>"
        f'<div class="cite">{_cell(fact.citation)}</div>{extra}{proof}'
        f"</details></td>"
        f"</tr>"
    )


def _section(
    anchor: str,
    title: str,
    facts: Sequence[Fact],
    root: Path,
) -> str:
    if not facts:
        return (
            f'<section id="{anchor}"><h2>{escape(title)}</h2>'
            '<div class="empty">Sin evidencia disponible: esta sección no se documenta y no se '
            "rellena con texto plausible.</div></section>"
        )
    body = "\n".join(_row(fact, root) for fact in facts)
    return (
        f'<section id="{anchor}"><h2>{escape(title)} '
        f'<span class="badge">{len(facts)}</span></h2>'
        "<table><thead><tr><th>Qué</th><th>Detalle</th><th>Evidencia</th></tr></thead>"
        f"<tbody>{body}</tbody></table></section>"
    )


def _shell(
    title: str,
    project: str,
    body: str,
    meta: Mapping[str, str],
    anchors: Sequence[tuple[str, str]] = (),
) -> str:
    links = " ".join(f'<a href="#{anchor}">{escape(label)}</a>' for anchor, label in anchors)
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · {escape(project)}</title>
<link rel="stylesheet" href="assets/site.css">
</head>
<body>
<header><div class="row">
<h1><a href="index.html">{escape(project)}</a> · {escape(title)}</h1>
<nav>{links}</nav>
<input type="search" id="q" placeholder="Buscar en el documento…" aria-label="Buscar">
<button id="expand" type="button">Expandir todo</button>
</div></header>
<main>
{body}
<footer>
Generado por docu {escape(meta.get('version', '0.1.0'))} · {escape(meta.get('facts', '0'))} afirmaciones
· {escape(meta.get('unsupported', '0'))} sin cita · fuente <code>{escape(meta.get('digest', '—'))}</code>.
<strong>Control del contenido:</strong> sólo se publica lo que tiene cita verificable; la profundidad
la elige quien lee.
</footer>
</main>
<script src="assets/site.js"></script>
</body>
</html>
"""


def parse_flowchart(text: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Lee el Mermaid que generamos (`flowchart LR`, `id["label"]`, `a --> b`).

    Se parsea nuestro propio formato a propósito: así la web comparte la misma evidencia que el
    documento en vez de mantener una segunda fuente de verdad.
    """
    nodes: list[tuple[str, str]] = []
    edges: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("flowchart") or stripped.startswith("%%"):
            continue
        if "-->" in stripped:
            left, _, right = stripped.partition("-->")
            edges.append((left.strip(), right.strip()))
            continue
        if '["' in stripped and stripped.endswith("]"):
            node, _, rest = stripped.partition('["')
            label = rest.rsplit('"]', 1)[0]
            nodes.append((node.strip(), label.replace("<br/>", " · ")))
    return nodes, edges


def svg_architecture(text: str, max_nodes: int = 24) -> str | None:
    """SVG del grafo de paquetes: columnas por profundidad, sin JavaScript ni CDN.

    Un diagrama que necesita red para verse no sirve en una revisión offline ni en un PDF; y uno que
    necesita un motor de JS para existir no se puede auditar. Este se genera del mismo grafo.
    """
    nodes, edges = parse_flowchart(text)
    if not nodes or len(nodes) > max_nodes:
        return None
    order = [name for name, _ in nodes]
    depth: dict[str, int] = {name: 0 for name in order}
    for _ in range(len(order)):  # relajación acotada: el grafo es pequeño y puede tener ciclos
        changed = False
        for source, target in edges:
            if source in depth and target in depth and depth[target] < depth[source] + 1:
                depth[target] = depth[source] + 1
                changed = True
        if not changed:
            break
    columns: dict[int, list[str]] = {}
    for name in order:
        columns.setdefault(depth[name], []).append(name)
    column_width, row_height, margin = 210, 46, 24
    positions: dict[str, tuple[int, int]] = {}
    for column, names in sorted(columns.items()):
        for row, name in enumerate(names):
            positions[name] = (margin + column * column_width, margin + row * row_height)
    width = margin * 2 + (max(columns) + 1) * column_width
    height = margin * 2 + max(len(names) for names in columns.values()) * row_height
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="Dependencias entre paquetes" xmlns="http://www.w3.org/2000/svg">',
        '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
        'markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#6ea8fe"/></marker></defs>',
    ]
    for source, target in edges:
        if source not in positions or target not in positions:
            continue
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        parts.append(
            f'<line x1="{x1 + 150}" y1="{y1 + 14}" x2="{x2}" y2="{y2 + 14}" '
            'stroke="#3a465c" stroke-width="1.2" marker-end="url(#a)"/>'
        )
    for name, label in nodes:
        x, y = positions[name]
        parts.append(
            f'<rect x="{x}" y="{y}" width="150" height="28" rx="6" fill="#151922" '
            'stroke="#2b3446"/>'
        )
        safe = escape(label)[:34]
        parts.append(
            f'<text x="{x + 8}" y="{y + 18}" fill="#e6e8ec" '
            f'font-family="ui-monospace,monospace" font-size="11">{safe}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def _diagrams_section(diagrams: Path, root: Path) -> str:
    """Diagramas ya generados junto a la documentación: SVG propio + código Mermaid copiable."""
    if not diagrams.is_dir():
        return ""
    blocks: list[str] = []
    for path in sorted(diagrams.glob("*.mmd")):
        text = path.read_text(encoding="utf-8")
        visual = svg_architecture(text) if path.stem == "arquitectura" else None
        title = path.stem.replace("-", " ").replace("_", ".")
        block = [f"<h3>{escape(title)}</h3>"]
        if visual:
            block.append(f'<div class="card">{visual}</div>')
        block.append(
            '<details><summary>Ver código Mermaid</summary>'
            f"<pre>{escape(text)}</pre></details>"
        )
        blocks.append("\n".join(block))
    if not blocks:
        return ""
    return (
        '<section id="diagramas"><h2>Diagramas '
        f'<span class="badge">{len(blocks)}</span></h2>'
        '<p class="cite">Generados del mismo grafo que el documento. El de arquitectura se dibuja '
        "como SVG propio: no necesita red ni JavaScript.</p>"
        + "\n".join(blocks)
        + "</section>"
    )


def build_site(
    root: Path | str,
    out_dir: Path | str,
    project: str,
    facts: Sequence[Fact],
    meta: Mapping[str, str] | None = None,
    levels: Sequence[str] = ("l1", "l2", "l4"),
    diagrams_dir: Path | str | None = None,
) -> tuple[Page, ...]:
    """Escribe la web y devuelve las páginas generadas."""
    root_path = Path(root).resolve()
    target = Path(out_dir)
    diagrams = Path(diagrams_dir) if diagrams_dir else target / "diagrams"
    assets = target / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "site.css").write_text(CSS, encoding="utf-8")
    (assets / "site.js").write_text(JS, encoding="utf-8")

    meta = dict(meta or {})
    counts = {}
    for fact in facts:
        counts[fact.kind] = counts.get(fact.kind, 0) + 1
    meta.setdefault("facts", str(len(facts)))

    pages: list[Page] = []
    for level in levels:
        wanted = LEVEL_SECTIONS.get(level, tuple(anchor for anchor, _, _ in SECTIONS))
        body: list[str] = []
        anchors: list[tuple[str, str]] = []
        for anchor, title, kinds in SECTIONS:
            if anchor not in wanted:
                continue
            selected = [fact for fact in facts if fact.kind in kinds]
            anchors.append((anchor, title))
            body.append(_section(anchor, title, _dedupe(selected), root_path))
        if level == "l1":
            diagram_section = _diagrams_section(diagrams, root_path)
            if diagram_section:
                anchors.append(("diagramas", "Diagramas"))
                body.append(diagram_section)
        name = f"{level}.html"
        content = _shell(f"Nivel {level[1]}", project, "\n".join(body), meta, anchors)
        (target / name).write_text(content, encoding="utf-8")
        pages.append(Page(name, f"Nivel {level[1]}", content))

    index_body = _index_body(project, facts, counts, meta, levels)
    index_html = _shell("Inicio", project, index_body, meta)
    (target / "index.html").write_text(index_html, encoding="utf-8")
    pages.insert(0, Page("index.html", "Inicio", index_html))

    payload = {
        "project": project,
        "version": meta.get("version", "0.1.0"),
        "digest": meta.get("digest", ""),
        "counts": counts,
        "facts": [
            {
                "kind": fact.kind,
                "subject": fact.subject,
                "detail": fact.detail,
                "citation": fact.citation,
            }
            for fact in facts
        ],
    }
    (target / "site.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return tuple(pages)


def _dedupe(facts: Sequence[Fact]) -> list[Fact]:
    seen: set[tuple[str, str, str]] = set()
    out: list[Fact] = []
    for fact in facts:
        key = (fact.kind, fact.subject, fact.citation)
        if key in seen:
            continue
        seen.add(key)
        out.append(fact)
    return out


def _index_body(
    project: str,
    facts: Sequence[Fact],
    counts: Mapping[str, int],
    meta: Mapping[str, str],
    levels: Sequence[str],
) -> str:
    cards = "\n".join(
        f'<div class="card"><div class="n">{count}</div><div class="l">{escape(label)}</div></div>'
        for label, count in (
            ("afirmaciones", len(facts)),
            ("con cita verificable", len(facts) - int(meta.get("unsupported", "0") or 0)),
            ("tipos documentados", counts.get("type", 0)),
            ("campos de datos", counts.get("field", 0)),
            ("rutas HTTP", counts.get("route", 0)),
        )
    )
    level_links = "\n".join(
        f'<li><a href="{level}.html">Nivel {level[1]}</a> — '
        + {
            "l1": "manual técnico: arquitectura, API, configuración, modelo de datos",
            "l2": "operación y despliegue: entorno, puertos, artefactos, CI",
            "l3": "guía de uso para quien no programa",
            "l4": "onboarding: lo mínimo para arrancar",
        }.get(level, "")
        + "</li>"
        for level in levels
    )
    return f"""
<p class="lead">Documentación de <strong>{escape(project)}</strong>. Cada afirmación se puede abrir
hasta el fragmento exacto del código que la sostiene: el contenido está controlado, la profundidad la
elige quien lee.</p>
<div class="grid">{cards}</div>
<h2>Cómo leer esto</h2>
<table><thead><tr><th>Escalón</th><th>Qué ves</th><th>Para qué</th></tr></thead><tbody>
<tr><td>1. Resumen</td><td>la fila: qué es y de qué tipo</td><td>orientarte rápido</td></tr>
<tr><td>2. Detalle</td><td>firma, anotaciones, valor declarado</td><td>trabajar con el dato</td></tr>
<tr><td>3. Prueba</td><td>la cita y el código real con números de línea</td><td>verificar sin creer</td></tr>
</tbody></table>
<h2>Documentos</h2>
<ul>{level_links}</ul>
<h2>Límites declarados</h2>
<p class="cite">Lo que el generador no cubre se publica como hueco explícito, nunca como prosa:
diagramas de secuencia, claves foráneas que el código no declare, e infraestructura provisionada fuera
del repositorio.</p>
"""


__all__ = [
    "CSS",
    "JS",
    "LEVEL_SECTIONS",
    "SECTIONS",
    "Page",
    "build_site",
    "escape",
    "parse_flowchart",
    "snippet",
    "svg_architecture",
]
