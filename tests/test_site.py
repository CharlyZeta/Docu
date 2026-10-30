"""Web de documentación: contenido controlado, profundidad bajo demanda y sin dependencias."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from docu.generate.facts import Fact
from docu.publish.site import (
    LEVEL_SECTIONS,
    build_site,
    escape,
    parse_erd,
    snippet,
    svg_api_flow,
    svg_erd,
)


def fact(kind: str, subject: str, detail: str, citation: str, **attributes: str) -> Fact:
    return Fact(kind=kind, subject=subject, detail=detail, citation=citation, attributes=attributes)


class EscapeTests(unittest.TestCase):
    def test_html_is_escaped(self) -> None:
        self.assertEqual(escape("<script>alert(1)</script>"), "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_quotes_are_escaped_for_attributes(self) -> None:
        self.assertEqual(escape('a"b'), "a&quot;b")


class SnippetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        body = "\n".join(f"linea {index}" for index in range(1, 61))
        (self.root / "src" / "demo.py").write_text(body + "\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_numbers_match_the_file(self) -> None:
        code = snippet(self.root, "src/demo.py#L10-L12")
        self.assertIn(">10</span>linea 10", code)
        self.assertIn(">12</span>linea 12", code)
        self.assertNotIn(">13</span>", code)

    def test_missing_file_returns_empty(self) -> None:
        self.assertEqual(snippet(self.root, "src/noexiste.py#L1-L2"), "")

    def test_malformed_citation_returns_empty(self) -> None:
        self.assertEqual(snippet(self.root, "src/demo.py"), "")

    def test_range_is_capped(self) -> None:
        code = snippet(self.root, "src/demo.py#L1-L60", limit=5)
        self.assertIn("linea 5", code)
        self.assertNotIn("linea 6", code)

    def test_markup_in_source_is_escaped(self) -> None:
        (self.root / "src" / "x.py").write_text('<b>hola</b>\n', encoding="utf-8")
        self.assertIn("&lt;b&gt;", snippet(self.root, "src/x.py#L1-L1"))


class BuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "demo.py").write_text("class Demo:\n    valor: int = 1\n", encoding="utf-8")
        self.facts = [
            fact("type", "Demo", "class", "src/demo.py#L1-L2"),
            fact("field", "Demo.valor", "int", "src/demo.py#L2-L2", owner="Demo"),
            fact("route", "GET /api/x", "Demo.get", "src/demo.py#L1-L2", verb="GET", path="/api/x"),
            fact("config_key", "server.port", "8080", "src/demo.py#L2-L2"),
        ]
        self.out = self.root / "site"
        self.pages = build_site(self.root, self.out, "demo", self.facts, meta={"version": "0.1.0"})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_pages_and_assets_are_written(self) -> None:
        names = {page.name for page in self.pages}
        self.assertEqual(names, {"index.html", "l1.html", "l2.html", "l4.html"})
        for asset in ("assets/site.css", "assets/site.js", "site.json"):
            self.assertTrue((self.out / asset).is_file(), msg=asset)

    def test_every_row_exposes_its_proof_in_a_details_block(self) -> None:
        html = (self.out / "l1.html").read_text(encoding="utf-8")
        self.assertIn("<summary>Ver prueba</summary>", html)
        self.assertIn("src/demo.py#L2-L2", html)
        self.assertIn("valor: int", html)  # fragmento real, no una descripción

    def test_level_pages_only_show_their_sections(self) -> None:
        l2 = (self.out / "l2.html").read_text(encoding="utf-8")
        self.assertNotIn("<h2>Tipo", l2)
        self.assertIn("Sin evidencia disponible", l2)  # operación no tiene hechos en el fixture
        self.assertIn("operacion", " ".join(LEVEL_SECTIONS["l2"]))

    def test_no_external_assets(self) -> None:
        for name in ("index.html", "l1.html", "l2.html", "l4.html"):
            html = (self.out / name).read_text(encoding="utf-8")
            self.assertNotIn('src="http', html, msg=name)
            self.assertNotIn('href="http', html, msg=name)

    def test_site_json_mirrors_the_facts(self) -> None:
        payload = json.loads((self.out / "site.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["project"], "demo")
        self.assertEqual(len(payload["facts"]), len(self.facts))
        self.assertEqual(payload["counts"]["field"], 1)

    def test_search_dataset_is_present(self) -> None:
        html = (self.out / "l1.html").read_text(encoding="utf-8")
        self.assertIn('data-search="', html)
        self.assertIn("demo.valor", html.lower())


class InjectionTests(unittest.TestCase):
    def test_fact_text_cannot_inject_markup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "site"
            facts = [fact("type", "<img src=x onerror=alert(1)>", "class", "a.py#L1-L1")]
            build_site(root, out, "demo", facts)
            html = (out / "l1.html").read_text(encoding="utf-8")
            self.assertNotIn("<img src=x", html)
            self.assertIn("&lt;img", html)


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "demo.py").write_text(
            "class Demo:\n    valor: int = 1\n\n    def metodo(self) -> int:\n        return 1\n",
            encoding="utf-8",
        )
        (self.root / "pyproject.toml").write_text(
            '[project]\nname = "demo"\ndependencies = ["requests"]\n', encoding="utf-8"
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_site_command_writes_the_web(self) -> None:
        from docu.delivery.cli import main

        out = self.root / "site"
        code = main(["site", "--root", str(self.root), "--out", str(out), "--level", "l1"])
        self.assertEqual(code, 0)
        self.assertTrue((out / "index.html").is_file())
        self.assertTrue((out / "l1.html").is_file())
        self.assertFalse((out / "l2.html").exists())
        self.assertTrue((out / "assets" / "site.css").is_file())

    def test_site_on_empty_project_fails_loudly(self) -> None:
        from docu.delivery.cli import main

        with tempfile.TemporaryDirectory() as empty:
            code = main(["site", "--root", empty, "--out", str(Path(empty) / "site")])
        self.assertEqual(code, 40)  # UNCITABLE_SOURCE


ERD = """erDiagram
    Cliente {
        String id
        String nombre
    }
    Pedido {
        String id
        Cliente cliente
    }
    Pedido }o--|| Cliente : "cliente"
"""

API_FLOW = """flowchart LR
    cliente(["Cliente"])
    r0["GET /api/x"]
    cliente --> r0
    h0["Ctl"]
    r0 --> h0
"""


class ErdSvgTests(unittest.TestCase):
    def test_parses_entities_and_relations(self) -> None:
        entities, relations = parse_erd(ERD)
        self.assertEqual(set(entities), {"Cliente", "Pedido"})
        self.assertEqual(len(entities["Pedido"]), 2)
        self.assertEqual(relations, [("Pedido", "}o--||", "Cliente", "cliente")])

    def test_draws_boxes_edge_and_cardinality(self) -> None:
        svg, note = svg_erd(ERD)
        assert svg is not None
        self.assertGreaterEqual(svg.count("<rect"), 2)
        self.assertGreaterEqual(svg.count("<line"), 1)
        self.assertIn("}o--||", svg)
        self.assertIn("Cliente", svg)
        self.assertEqual(note, "")

    def test_truncation_is_declared(self) -> None:
        many = "erDiagram\n" + "\n".join(
            f"    T{index} {{\n        String id\n    }}" for index in range(30)
        )
        svg, note = svg_erd(many, max_entities=5)
        assert svg is not None
        self.assertIn("se muestran 5 de 30 entidades", note)

    def test_relations_prioritise_connected_entities(self) -> None:
        text = "erDiagram\n" + "\n".join(
            f"    Grande{index} {{\n" + "\n".join(f"        String f{row}" for row in range(6)) + "\n    }"
            for index in range(12)
        )
        text += '\n    A {\n        String id\n    }\n    B {\n        String id\n    }\n'
        text += '    A }o--|| B : "b"'
        svg, _note = svg_erd(text, max_entities=4)
        assert svg is not None
        self.assertIn("A", svg)
        self.assertIn("B", svg)

    def test_without_entities_returns_nothing(self) -> None:
        self.assertEqual(svg_erd(""), (None, ""))


class ApiFlowSvgTests(unittest.TestCase):
    def test_draws_client_route_and_handler(self) -> None:
        svg, note = svg_api_flow(API_FLOW)
        assert svg is not None
        self.assertIn("Cliente", svg)
        self.assertIn("GET /api/x", svg)
        self.assertIn("Ctl", svg)
        self.assertGreaterEqual(svg.count("<line"), 2)
        self.assertEqual(note, "")

    def test_caps_routes_and_says_so(self) -> None:
        lines = ['flowchart LR', '    cliente(["Cliente"])']
        for index in range(20):
            lines += [f'    r{index}["GET /api/{index}"]', f"    cliente --> r{index}", f'    h0["Ctl"]', f"    r{index} --> h0"]
        svg, note = svg_api_flow("\n".join(lines), max_routes=5)
        assert svg is not None
        self.assertIn("se muestran 5 de 20 rutas", note)

    def test_without_routes_returns_nothing(self) -> None:
        self.assertEqual(svg_api_flow('flowchart LR\n    cliente(["Cliente"])'), (None, ""))


class DiagramsInSiteTests(unittest.TestCase):
    def test_three_diagrams_are_drawn_and_all_are_copyable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "demo.py").write_text("class Demo:\n    valor: int = 1\n", encoding="utf-8")
            diagrams = root / "docs" / "diagrams"
            diagrams.mkdir(parents=True)
            (diagrams / "arquitectura.mmd").write_text(
                'flowchart LR\n    a["a"]\n    b["b"]\n    a --> b\n', encoding="utf-8"
            )
            (diagrams / "modelo-de-datos.mmd").write_text(ERD, encoding="utf-8")
            (diagrams / "api-flujo.mmd").write_text(API_FLOW, encoding="utf-8")
            (diagrams / "clases-demo.mmd").write_text("classDiagram\n    class Demo", encoding="utf-8")

            out = root / "site"
            build_site(
                root,
                out,
                "demo",
                [fact("type", "Demo", "class", "src/demo.py#L1-L2")],
                levels=("l1",),
                diagrams_dir=diagrams,
            )
            html = (out / "l1.html").read_text(encoding="utf-8")
            self.assertEqual(html.count("<svg"), 3)
            self.assertEqual(html.count("Ver código Mermaid"), 4)
            self.assertIn("3 se dibujan como SVG propio", html)


if __name__ == "__main__":
    unittest.main()
