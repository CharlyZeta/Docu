"""Buscador de documentación: lo que consumen el servidor MCP y, más adelante, el CLI."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docu.retrieve.search import DocIndex, Section, split_sections, tokenize

DOC = """# demo — Manual técnico

Cabecera sin sección real.

## 1. Resumen

- Rutas HTTP: **2**

## 4. API HTTP

| Verbo | Ruta | Cita |
|---|---|---|
| POST | `/api/auth/refresh` | `Auth.java#L35-L40` |

## 5. Configuración

| Clave | Valor | Cita |
|---|---|---|
| `bss.security.jwt.secret` | `abc` | `application.yml#L15-L15` |
"""


class TokenizeTests(unittest.TestCase):
    def test_folding_and_camel(self) -> None:
        tokens = tokenize("Configuración BssSecurityFilter")
        self.assertIn("configuracion", tokens)
        self.assertIn("security", tokens)

    def test_stopwords(self) -> None:
        self.assertNotIn("de", tokenize("la configuración de la API"))


class SplitTests(unittest.TestCase):
    def test_sections_follow_h2_headings(self) -> None:
        sections = split_sections(Path("l1-manual-tecnico.md"), DOC, "l1")
        headings = [section.heading for section in sections]
        self.assertIn("4. API HTTP", headings)
        self.assertIn("5. Configuración", headings)

    def test_citations_are_collected(self) -> None:
        sections = split_sections(Path("l1.md"), DOC, "l1")
        api = next(section for section in sections if section.heading == "4. API HTTP")
        self.assertIn("Auth.java#L35-L40", api.citations)

    def test_level_is_recorded(self) -> None:
        sections = split_sections(Path("l3-guia.md"), DOC, "l3")
        self.assertTrue(all(section.level == "l3" for section in sections))


class IndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.docs = Path(self._tmp.name)
        (self.docs / "l1-manual-tecnico.md").write_text(DOC, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_search_finds_the_right_section(self) -> None:
        index = DocIndex.from_directory(self.docs)
        hits = index.search("configuración del secreto del jwt")
        self.assertTrue(hits)
        self.assertEqual(hits[0][0].heading, "5. Configuración")

    def test_search_finds_routes(self) -> None:
        index = DocIndex.from_directory(self.docs)
        hits = index.search("api auth refresh")
        self.assertEqual(hits[0][0].heading, "4. API HTTP")

    def test_level_filter(self) -> None:
        index = DocIndex.from_directory(self.docs)
        self.assertEqual(index.search("api", level="l4"), [])

    def test_unknown_term_returns_nothing(self) -> None:
        index = DocIndex.from_directory(self.docs)
        self.assertEqual(index.search("ornitorrinco"), [])

    def test_empty_directory(self) -> None:
        empty = self.docs / "vacio"
        empty.mkdir()
        index = DocIndex.from_directory(empty)
        self.assertTrue(index.is_empty)
        self.assertEqual(index.search("cualquier cosa"), [])

    def test_glossary_expansion_is_applied_by_default(self) -> None:
        index = DocIndex.from_directory(self.docs)
        with_glossary = index.search("cadena de filtros")
        without = index.search("cadena de filtros", expand_query=False)
        self.assertGreaterEqual(len(with_glossary), len(without))

    def test_section_serialization(self) -> None:
        section = Section(document="l1.md", heading="X", body="cuerpo `a.java#L1-L2`")
        payload = section.to_dict()
        self.assertEqual(payload["heading"], "X")


if __name__ == "__main__":
    unittest.main()
