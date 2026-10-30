"""Intención y decisiones: prosa derivada de lo que el proyecto ya declaró."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docu.generate.narrative import (
    Narrative,
    collect,
    doc_facts,
    why_comments,
)

README = """# Mi Proyecto

[![CI](https://img.shields.io/badge/ci-ok-brightgreen)](https://example.com)
![Licencia](https://img.shields.io/badge/licencia-MIT-green)

Plataforma de gestión comercial omnicanal para equipos de ventas que necesitan
operar ventas físicas y tiendas en línea desde un solo lugar.

## Instalación

Otra cosa que no es la introducción.
"""

ADR = """# ADR 0007: usar cola de eventos para el tracking

Status: Accepted

Decidimos publicar eventos en una cola en lugar de consultar la API del proveedor en cada
petición, porque la latencia del proveedor dominaba el tiempo de respuesta.
"""

JAVA = """package com.example;

/**
 * Servicio que resuelve el saldo de una cuenta corriente.
 * Se mantiene separado del controlador para poder probarlo sin HTTP.
 */
public class SaldoService {
}
"""

PYTHON = '''
"""Módulo de frescura: decide si una página está al día."""

# Se calcula sobre contenido normalizado para no contar CRLF dos veces.
# Es importante porque el mismo commit debe validar en Windows y en Linux.


class Frescura:
    """Compara la huella guardada con la actual."""
'''

PY_CON_STRING = '''
MENSAJE = "esto explica porque algo pasa pero es una cadena, no un comentario"
'''


class DocTests(unittest.TestCase):
    def test_readme_intent_skips_badges_and_headings(self) -> None:
        facts = doc_facts("README.md", README)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].kind, "intent")
        self.assertIn("gestión comercial omnicanal", facts[0].detail)
        self.assertNotIn("shields.io", facts[0].detail)
        self.assertNotIn("Mi Proyecto", facts[0].detail)

    def test_citation_points_to_the_paragraph(self) -> None:
        facts = doc_facts("README.md", README)
        line = int(facts[0].citation.split("#L")[1].split("-")[0])
        self.assertEqual(README.splitlines()[line - 1][:20], "Plataforma de gestió")

    def test_adr_is_a_decision_with_status(self) -> None:
        facts = doc_facts("docs/adr/0007-cola.md", ADR)
        self.assertEqual(facts[0].kind, "decision")
        self.assertEqual(facts[0].attributes["status"], "Accepted")
        self.assertIn("cola de eventos", facts[0].subject.lower())

    def test_document_without_prose_yields_nothing(self) -> None:
        self.assertEqual(doc_facts("NOTAS.md", "# Título\n\n- item\n- item\n"), [])


class CommentTests(unittest.TestCase):
    def test_python_comment_with_why_is_a_decision(self) -> None:
        facts = why_comments("src/frescura.py", PYTHON)
        self.assertTrue(facts)
        self.assertTrue(any("CRLF" in fact.detail for fact in facts))
        self.assertTrue(all(fact.kind == "decision" for fact in facts))

    def test_string_with_why_is_not_a_decision(self) -> None:
        """La regresión que importa: un `porque` dentro de una cadena no es una decisión."""
        self.assertEqual(why_comments("src/mensajes.py", PY_CON_STRING), [])

    def test_comment_without_why_word_is_ignored(self) -> None:
        self.assertEqual(why_comments("x.py", "# solo un comentario cualquiera del archivo\n"), [])

    def test_causal_words_are_recognised(self) -> None:
        for phrase in ("sin motivo aparente", "para no romper el CI", "en lugar de consultar"):
            with self.subTest(phrase=phrase):
                text = f"# Se eligió esto {phrase} en el flujo principal\n"
                self.assertTrue(why_comments("x.py", text))


class DocstringTests(unittest.TestCase):
    def test_javadoc_becomes_intent(self) -> None:
        from docu.generate.narrative import _javadoc_facts

        facts = _javadoc_facts("SaldoService.java", JAVA)
        self.assertTrue(facts)
        self.assertIn("cuenta corriente", facts[0].detail)
        self.assertTrue(facts[0].citation.startswith("SaldoService.java#L3"))

    def test_python_docstrings_become_intent(self) -> None:
        from docu.generate.narrative import _python_docstring_facts

        facts = _python_docstring_facts("src/frescura.py", PYTHON)
        self.assertTrue(facts)
        subjects = {fact.subject for fact in facts}
        self.assertIn("Frescura", subjects)
        self.assertTrue(any("módulo" in subject for subject in subjects))


class CollectTests(unittest.TestCase):
    def test_intro_cites_readme_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(README, encoding="utf-8")
            narrative = collect(
                root, {}, {"package": 3, "type": 5, "field": 9}, "demo", lambda path: path.read_text(encoding="utf-8")
            )
            self.assertIn("**demo** se compone de 3 paquetes, 5 tipos y 9 campos.", narrative.intro)
            self.assertIn("README.md#L", narrative.intro)
            self.assertIn("gestión comercial", narrative.intro)

    def test_without_evidence_the_intro_declares_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            narrative = collect(Path(tmp), {}, {"package": 1}, "vacio", lambda path: "")
            self.assertIn("no declara", narrative.intro)
            self.assertEqual(narrative.intent, [])
            self.assertEqual(narrative.decisions, [])

    def test_facts_property_combines_both(self) -> None:
        narrative = Narrative(intent=[], decisions=[])
        self.assertEqual(narrative.facts, [])


class RenderTests(unittest.TestCase):
    def test_sections_appear_with_their_citations(self) -> None:
        from docu.generate.facts import Fact
        from docu.generate.markdown import render_l1

        facts = [
            Fact("intent", "Mi Proyecto", "Plataforma omnicanal", "README.md#L5-L7"),
            Fact("decision", "Usar cola de eventos", "Accepted · por latencia", "docs/adr/1.md#L1-L5"),
        ]
        document = render_l1("demo", facts, {}, {"intro": "**demo** se compone de 3 paquetes."})
        self.assertIn("## 1. Introducción", document)
        self.assertIn("## 3. Intención y decisiones", document)
        self.assertIn("Plataforma omnicanal", document)
        self.assertIn("Usar cola de eventos", document)
        self.assertIn("README.md#L5-L7", document)

    def test_without_narrative_the_gap_is_declared(self) -> None:
        from docu.generate.markdown import render_l1

        document = render_l1("demo", [], {}, {})
        self.assertIn("no declara su intención", document)


if __name__ == "__main__":
    unittest.main()
