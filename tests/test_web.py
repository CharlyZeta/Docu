"""Ingesta web: snapshot congelado, allowlist y cita verificable sin red."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from docu.adapters.sources.web import (
    MIN_TEXT_CHARS,
    WebError,
    capture,
    html_to_text,
    is_allowed,
)
from docu.index.webdocs import capture_urls, check_stale, load_documents, read_index, web_facts

HTML = """<!doctype html>
<html><head><title>Manual</title><script>var x = 1;</script>
<style>.a{color:red}</style></head>
<body>
<nav><a href="/">Inicio</a></nav>
<h1>Guía de la API</h1>
<p>La función <code>evaluate()</code> decide si una página está fresca.</p>
<ul><li>Primer criterio</li><li>Segundo criterio</li></ul>
<footer>Pie repetido</footer>
<footer>Pie repetido</footer>
</body></html>
"""

LONG = "<html><body>" + "".join(f"<p>Parrafo numero {index} con contenido suficiente.</p>" for index in range(20)) + "</body></html>"


class Opener:
    """Doble de `urlopen` para no depender de la red en los tests."""

    def __init__(self, body: str, status: int = 200) -> None:
        self.body = body.encode("utf-8")
        self.status = status

    def __call__(self, request, timeout=None):  # noqa: ARG002
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        return self.body[:limit] if limit and limit > 0 else self.body


class TextTests(unittest.TestCase):
    def test_scripts_styles_and_nav_are_dropped(self) -> None:
        text = html_to_text(HTML)
        self.assertNotIn("var x = 1", text)
        self.assertNotIn("color:red", text)
        self.assertNotIn("Inicio", text)  # nav fuera
        self.assertIn("Guía de la API", text)

    def test_blocks_become_lines(self) -> None:
        text = html_to_text(HTML)
        self.assertIn("Primer criterio", text)
        self.assertIn("Segundo criterio", text)
        self.assertGreaterEqual(text.count("\n"), 3)

    def test_entities_are_decoded(self) -> None:
        self.assertIn("a & b", html_to_text("<p>a &amp; b</p>"))

    def test_adjacent_duplicate_lines_are_collapsed(self) -> None:
        text = html_to_text("<p>Mismo texto</p><p>Mismo texto</p><p>Otro</p>")
        self.assertEqual(text.count("Mismo texto"), 1)
        self.assertIn("Otro", text)


class AllowlistTests(unittest.TestCase):
    def test_exact_and_subdomain(self) -> None:
        self.assertTrue(is_allowed("https://docs.python.org/3/", ("docs.python.org",)))
        self.assertTrue(is_allowed("https://es.docs.spring.io/x", ("spring.io",)))

    def test_outside_allowlist_is_blocked(self) -> None:
        self.assertFalse(is_allowed("https://example.com/doc", ("docs.python.org",)))

    def test_other_schemes_are_blocked(self) -> None:
        self.assertFalse(is_allowed("file:///etc/passwd", ("docs.python.org",)))
        self.assertFalse(is_allowed("ftp://docs.python.org/x", ("docs.python.org",)))

    def test_lookalike_domain_is_blocked(self) -> None:
        self.assertFalse(is_allowed("https://evildocs.python.org.attacker.com/x", ("python.org",)))


class CaptureTests(unittest.TestCase):
    def test_capture_returns_snapshot_with_hash(self) -> None:
        snapshot = capture("https://docs.python.org/3/", ("docs.python.org",), opener=Opener(LONG))
        self.assertEqual(snapshot.status_code, 200)
        self.assertTrue(snapshot.usable)
        self.assertEqual(len(snapshot.sha), 64)
        self.assertTrue(snapshot.slug.startswith("docs-python-org"))
        self.assertIn("Parrafo numero 3", snapshot.text)

    def test_blocked_domain_raises(self) -> None:
        with self.assertRaises(WebError):
            capture("https://example.com/x", ("docs.python.org",), opener=Opener(LONG))

    def test_empty_page_raises_instead_of_documenting_nothing(self) -> None:
        with self.assertRaises(WebError) as ctx:
            capture("https://docs.python.org/x", ("docs.python.org",), opener=Opener("<html><body></body></html>"))
        self.assertIn("no tiene texto útil", str(ctx.exception))

    def test_minimum_chars_is_enforced(self) -> None:
        with self.assertRaises(WebError):
            capture("https://docs.python.org/x", ("docs.python.org",), opener=Opener("<p>corto</p>"))
        self.assertGreater(MIN_TEXT_CHARS, 10)


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.docs = self.root / "docs"
        self.url = "https://docs.python.org/3/library/ast.html"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_capture_writes_snapshot_and_index(self) -> None:
        documents, errors = capture_urls(
            self.root, [self.url], ("docs.python.org",), self.docs, opener=Opener(LONG)
        )
        self.assertEqual(errors, [])
        self.assertTrue(documents[0].usable)
        self.assertTrue((self.root / documents[0].rel).is_file())
        index = read_index(self.root)
        self.assertIn(self.url, index)
        self.assertEqual(index[self.url]["sha"], documents[0].sha)

    def test_generation_reads_snapshots_without_network(self) -> None:
        capture_urls(self.root, [self.url], ("docs.python.org",), self.docs, opener=Opener(LONG))
        documents = load_documents(self.root, [self.url])
        self.assertTrue(documents[0].usable)
        facts = web_facts(documents)
        self.assertEqual(facts[0].kind, "web_source")
        self.assertTrue(facts[0].citation.endswith("#L1-L" + str(documents[0].lines)))

    def test_missing_snapshot_is_declared(self) -> None:
        documents = load_documents(self.root, [self.url])
        self.assertFalse(documents[0].usable)
        self.assertIn("--fetch", documents[0].error)
        self.assertEqual(web_facts(documents), [])

    def test_failed_capture_keeps_previous_snapshot(self) -> None:
        capture_urls(self.root, [self.url], ("docs.python.org",), self.docs, opener=Opener(LONG))
        documents, errors = capture_urls(
            self.root, [self.url], ("docs.python.org",), self.docs, opener=Opener("<p>corto</p>")
        )
        self.assertTrue(errors)
        self.assertTrue(documents[0].usable)  # se conserva lo ya congelado

    def test_check_detects_changes(self) -> None:
        capture_urls(self.root, [self.url], ("docs.python.org",), self.docs, opener=Opener(LONG))
        same = check_stale(self.root, ("docs.python.org",), opener=Opener(LONG))
        changed = check_stale(
            self.root, ("docs.python.org",), opener=Opener(LONG.replace("Parrafo", "Párrafo"))
        )
        self.assertEqual(same[0][1], "vigente")
        self.assertIn("cambió", changed[0][1])


class ResolveTests(unittest.TestCase):
    def test_out_dir_is_relative_to_the_project_not_the_cwd(self) -> None:
        """`--root` a otro proyecto no debe escribir en el directorio actual."""
        import argparse

        from docu.delivery.cli import _resolve

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docu.profile.yaml").write_text(
                'schema_version: "1.0"\nproject: demo\noutput:\n  dir: docs/generated\n', encoding="utf-8"
            )
            options = _resolve(argparse.Namespace(root=str(root)), root)
            self.assertEqual(options.out_dir, root / "docs" / "generated")
            self.assertTrue(options.out_dir.is_absolute())


class PipelineTests(unittest.TestCase):
    def test_web_source_appears_in_the_document(self) -> None:
        from docu.delivery.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "demo.py").write_text("class Demo:\n    valor: int = 1\n", encoding="utf-8")
            profile = root / "docu.profile.yaml"
            profile.write_text(
                'schema_version: "1.0"\nproject: demo\n'
                "sources:\n  web:\n    allowlist: [docs.python.org]\n"
                "    urls: [https://docs.python.org/3/library/ast.html]\n",
                encoding="utf-8",
            )
            capture_urls(
                root, ["https://docs.python.org/3/library/ast.html"], ("docs.python.org",), root / "docs" / "generated", opener=Opener(LONG)
            )
            code = main(["gen", "--root", str(root), "--level", "l1"])
            self.assertEqual(code, 0)
            document = (root / "docs" / "generated" / "l1-manual-tecnico.md").read_text(encoding="utf-8")
            self.assertIn("## 10. Documentos y fuentes de referencia", document)
            self.assertIn("https://docs.python.org/3/library/ast.html", document)
            self.assertIn("web/docs-python-org", document)


if __name__ == "__main__":
    unittest.main()
