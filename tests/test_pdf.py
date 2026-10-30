"""Ingesta de PDF: texto extraíble, límites declarados y citas por página."""

from __future__ import annotations

import unittest
import zlib
from pathlib import Path

from docu.adapters.sources.pdf import extract, is_pdf, pages_text


def make_pdf(content: bytes, compress: bool = False, extra_objects: bytes = b"") -> bytes:
    """PDF mínimo válido: catálogo, árbol de páginas, una página y su content stream."""
    stream = zlib.compress(content) if compress else content
    filter_ = b"/Filter /FlateDecode " if compress else b""
    objects = (
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [4 0 R] /Count 1 >>\nendobj\n"
        b"4 0 obj\n<< /Type /Page /Contents 3 0 R >>\nendobj\n"
        b"3 0 obj\n<< /Length " + str(len(stream)).encode() + b" " + filter_ + b">>\nstream\n"
        + stream
        + b"\nendstream\nendobj\n"
        + extra_objects
    )
    return b"%PDF-1.4\n" + objects + b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"


TEXT_CONTENT = b"BT /F1 12 Tf 40 700 Td (Hola mundo desde un PDF) Tj ET"


class DetectTests(unittest.TestCase):
    def test_by_extension_and_magic(self) -> None:
        self.assertTrue(is_pdf("manual.PDF"))
        self.assertTrue(is_pdf("x.bin", b"%PDF-1.7 ..."))
        self.assertFalse(is_pdf("x.txt", b"texto"))


class ExtractionTests(unittest.TestCase):
    def test_uncompressed_pdf(self) -> None:
        result = extract(make_pdf(TEXT_CONTENT))
        self.assertEqual(result.total_pages, 1)
        self.assertIn("Hola mundo desde un PDF", result.pages[0].text)
        self.assertTrue(result.usable)
        self.assertEqual(result.method, "sin comprimir")

    def test_flate_compressed_pdf(self) -> None:
        result = extract(make_pdf(TEXT_CONTENT, compress=True))
        self.assertIn("Hola mundo", result.pages[0].text)
        self.assertIn("FlateDecode", result.method)

    def test_tj_array_joins_text(self) -> None:
        content = b"BT [(Hola) -200 (mundo)] TJ ET"
        self.assertIn("Hola mundo", extract(make_pdf(content)).pages[0].text)

    def test_escaped_parentheses(self) -> None:
        content = b"BT (linea \\(1\\) y \\(2\\)) Tj ET"
        self.assertIn("linea (1) y (2)", extract(make_pdf(content)).pages[0].text)

    def test_hex_string(self) -> None:
        content = b"BT <48656C6C6F> Tj ET"
        self.assertIn("Hello", extract(make_pdf(content)).pages[0].text)

    def test_octal_escape(self) -> None:
        content = b"BT (caf\\351) Tj ET"
        self.assertIn("café", extract(make_pdf(content)).pages[0].text)

    def test_single_quote_operator_adds_line(self) -> None:
        content = b"BT (uno) Tj ET BT (dos) ' ET"
        text = extract(make_pdf(content)).pages[0].text
        self.assertIn("uno", text)
        self.assertIn("dos", text)

    def test_tounicode_cmap(self) -> None:
        cmap = (
            b"9 0 obj\n<< /Length 60 >>\nstream\n"
            b"beginbfchar\n<41> <0058>\n<42> <0059>\nendbfchar\n"
            b"endstream\nendobj\n"
        )
        content = b"BT <4142> Tj ET"
        result = extract(make_pdf(content, extra_objects=cmap))
        self.assertIn("XY", result.pages[0].text)
        self.assertIn("ToUnicode", result.method)


class LimitTests(unittest.TestCase):
    def test_scanned_pdf_is_declared_not_invented(self) -> None:
        result = extract(make_pdf(b"q 1 0 0 1 0 0 cm /Im0 Do Q"))
        self.assertFalse(result.usable)
        self.assertEqual(result.chars, 0)
        self.assertIn("escaneado", result.status)
        self.assertTrue(result.warnings)

    def test_encrypted_pdf_is_declared(self) -> None:
        data = make_pdf(TEXT_CONTENT).replace(b"trailer", b"trailer\n<< /Encrypt 9 0 R >>")
        result = extract(data)
        self.assertFalse(result.usable)
        self.assertIn("cifrado", " ".join(result.warnings))

    def test_not_a_pdf_is_declared(self) -> None:
        result = extract(b"no soy un pdf")
        self.assertFalse(result.usable)
        self.assertIn("%PDF", " ".join(result.warnings))

    def test_empty_bytes_do_not_raise(self) -> None:
        self.assertFalse(extract(b"").usable)


class SidecarTests(unittest.TestCase):
    def test_pages_are_separated(self) -> None:
        text = pages_text(extract(make_pdf(TEXT_CONTENT)))
        self.assertIn("--- página 1 ---", text)
        self.assertIn("Hola mundo", text)


class IntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "demo.py").write_text("class Demo:\n    valor: int = 1\n", encoding="utf-8")
        (self.root / "docs").mkdir()
        (self.root / "docs" / "manual.pdf").write_bytes(make_pdf(TEXT_CONTENT))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_generation_lists_the_pdf_with_page_citation(self) -> None:
        from docu.delivery.cli import main

        out = self.root / "generated"
        code = main(["gen", "--root", str(self.root), "--out", str(out), "--level", "l1"])
        self.assertEqual(code, 0)
        document = (out / "l1-manual-tecnico.md").read_text(encoding="utf-8")
        self.assertIn("## 12. Documentos y fuentes de referencia", document)
        self.assertIn("docs/manual.pdf#p1", document)

    def test_pdf_command_writes_the_sidecar(self) -> None:
        from docu.delivery.cli import main

        out = self.root / "generated"
        code = main(["pdf", "--root", str(self.root), "--out", str(out)])
        self.assertEqual(code, 0)
        sidecar = out / "pdf" / "docs__manual.txt"
        self.assertTrue(sidecar.is_file())
        self.assertIn("Hola mundo", sidecar.read_text(encoding="utf-8"))

    def test_pdf_without_text_fails_loudly(self) -> None:
        from docu.delivery.cli import main

        (self.root / "docs" / "manual.pdf").write_bytes(make_pdf(b"q 1 0 0 1 0 0 cm /Im0 Do Q"))
        code = main(["pdf", "--root", str(self.root), "--out", str(self.root / "generated")])
        self.assertEqual(code, 40)  # UNCITABLE_SOURCE

    def test_pdf_hash_affects_freshness(self) -> None:
        from docu.generate.pipeline import collect_facts

        _facts, sources = collect_facts(self.root)
        self.assertIn("docs/manual.pdf", sources)
        (self.root / "docs" / "manual.pdf").write_bytes(make_pdf(TEXT_CONTENT + b" mas texto"))
        _facts2, sources2 = collect_facts(self.root)
        self.assertNotEqual(sources["docs/manual.pdf"], sources2["docs/manual.pdf"])


if __name__ == "__main__":
    unittest.main()
