"""Web de documentación: contenido controlado, profundidad bajo demanda y sin dependencias."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from docu.generate.facts import Fact
from docu.publish.site import LEVEL_SECTIONS, build_site, escape, snippet


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


if __name__ == "__main__":
    unittest.main()
