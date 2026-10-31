"""La documentación existente del repositorio como evidencia citada (hallazgo F-06)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docu.generate.docs_evidence import (
    PREREQUISITE_HINTS,
    SETUP_HINTS,
    discover,
    find,
    parse_sections,
)

README = """# SalesHub

Plataforma de gestión comercial omnicanal para equipos de venta que operan ventas físicas
y tiendas en línea desde un solo lugar, con integraciones de comercio electrónico.

## 🚀 Guía de Instalación y Ejecución Local

Cómo levantar el proyecto en una máquina nueva.

### Prerrequisitos:

- **Node.js**: v20.0.0 o superior
- **npm**: v10.0.0 o superior

### Pasos de Instalación:

1. Clonar el repositorio
2. `npm install`
3. `npm run dev`

## Resumen de Cobertura de Pruebas (reporte `npm run test:coverage`):

> La cobertura mide la lógica pura y no los componentes de UI.
"""


class ParseTests(unittest.TestCase):
    def test_sections_have_body_and_citation(self) -> None:
        sections = parse_sections("README.md", README)
        titles = [section.title for section in sections]
        self.assertIn("Prerrequisitos:", titles)
        prereq = next(section for section in sections if section.title == "Prerrequisitos:")
        self.assertIn("Node.js", prereq.body)
        self.assertRegex(prereq.citation, r"^README\.md#L\d+-L\d+$")

    def test_badges_and_images_are_not_body(self) -> None:
        sections = parse_sections("README.md", "# T\n\n[![CI](x)](y)\n\nTexto real y suficiente.\n")
        self.assertNotIn("shields", sections[0].body)
        self.assertIn("Texto real", sections[0].body)

    def test_deep_headings_are_ignored(self) -> None:
        sections = parse_sections("README.md", "# A\n\n#### Muy profundo\n\nCuerpo.\n")
        self.assertEqual([section.title for section in sections], ["A"])


class DiscoverTests(unittest.TestCase):
    def test_readme_is_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(README, encoding="utf-8")
            sections = discover(root)
            self.assertTrue(any(section.title == "Prerrequisitos:" for section in sections))

    def test_docs_directory_is_read_but_generated_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "guia.md").write_text("# Guía\n\nContenido suficiente para la prueba.\n", encoding="utf-8")
            (root / "docs" / "generated").mkdir()
            (root / "docs" / "generated" / "l1.md").write_text("# Generado\n\nNo debe aparecer.\n", encoding="utf-8")
            titles = [section.title for section in discover(root)]
            self.assertIn("Guía", titles)
            self.assertNotIn("Generado", titles)

    def test_missing_files_do_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(discover(Path(tmp)), [])


class MatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sections = parse_sections("README.md", README)

    def test_prerequisites_match_by_title(self) -> None:
        matched = find(self.sections, PREREQUISITE_HINTS)
        self.assertTrue(matched)
        self.assertIn("Prerrequisitos:", [section.title for section in matched])

    def test_coverage_report_is_not_setup(self) -> None:
        """Un reporte de cobertura menciona `npm run`, pero no es la puesta en marcha."""
        matched = find(self.sections, SETUP_HINTS)
        self.assertNotIn(
            "Resumen de Cobertura de Pruebas (reporte `npm run test:coverage`):",
            [section.title for section in matched],
        )

    def test_no_match_returns_empty(self) -> None:
        self.assertEqual(find(self.sections, ("kubernetes",)), [])


class RenderTests(unittest.TestCase):
    def test_l4_fills_prerequisites_with_the_repository_readme(self) -> None:
        from docu.generate.facts import Fact
        from docu.generate.markdown import render_l4

        sections = {section.title: section for section in parse_sections("README.md", README)}
        facts = [sections["Prerrequisitos:"].to_fact()]
        document = render_l4("demo", facts, {}, {})
        section = document.split("## Prerrequisitos")[1].split("##")[0]
        self.assertIn("ya documenta", section)
        self.assertIn("README.md#L", section)
        self.assertIn("Node.js", section)

    def test_l4_falls_back_to_the_gap_when_nothing_matches(self) -> None:
        from docu.generate.markdown import render_l4

        document = render_l4("demo", [], {}, {})
        self.assertIn("Sin evidencia", document)


if __name__ == "__main__":
    unittest.main()
