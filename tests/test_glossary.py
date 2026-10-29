"""Glosario de dominio: la palanca que mas mueve el recall en espanol."""

from __future__ import annotations

import unittest

from docu.retrieve.glossary import DEFAULT_GLOSSARY, expand, fold, merge


class ExpandTests(unittest.TestCase):
    def test_known_phrase_adds_code_terms(self) -> None:
        expanded = expand("¿Dónde se define la cadena de filtros?")
        self.assertIn("securityfilterchain", expanded)
        self.assertIn("filter", expanded)

    def test_multiple_phrases_accumulate_without_duplicates(self) -> None:
        expanded = expand("el secreto del JWT y el filtro")
        terms = expanded.split()
        self.assertEqual(terms.count("filter"), 1)

    def test_unknown_query_is_returned_unchanged(self) -> None:
        query = "cosa completamente ajena al dominio"
        self.assertEqual(expand(query), query)

    def test_original_query_is_preserved_as_prefix(self) -> None:
        query = "puerto de la aplicación"
        self.assertTrue(expand(query).startswith(query))

    def test_matching_respects_word_boundaries(self) -> None:
        # `cors` no debe expandir dentro de otra palabra.
        self.assertEqual(expand("corsario"), "corsario")
        self.assertIn("cors", expand("configuración de cors"))

    def test_matching_is_accent_insensitive(self) -> None:
        plain = expand("expiracion del token")
        accented = expand("expiración del token")
        # La consulta original se conserva tal cual; lo que debe coincidir son los terminos anadidos.
        self.assertEqual(plain.split(" ", 3)[3], accented.split(" ", 3)[3])
        self.assertIn("expiration", accented)

    def test_plural_is_a_documented_limitation(self) -> None:
        # El glosario es estricto por palabra: "filtros" no dispara "filtro".
        # Se documenta como limitacion conocida para que se declare la frase con su plural.
        self.assertNotIn("onceperrequestfilter", expand("filtros"))

    def test_injected_glossary_replaces_default(self) -> None:
        custom = {"cosa": ("thing",)}
        self.assertIn("thing", expand("esa cosa", custom))
        self.assertNotIn("securityfilterchain", expand("la cadena de filtros", custom))


class FoldTests(unittest.TestCase):
    def test_diacritics_are_removed(self) -> None:
        self.assertEqual(fold("configuración"), "configuracion")
        self.assertEqual(fold("expiración"), "expiracion")


class MergeTests(unittest.TestCase):
    def test_profile_glossary_extends_default(self) -> None:
        merged = merge(DEFAULT_GLOSSARY, {"puerto": ("servlet",), "nuevo termino": ("newterm",)})
        self.assertIn("port", merged["puerto"])
        self.assertIn("servlet", merged["puerto"])
        self.assertEqual(merged["nuevo termino"], ("newterm",))

    def test_default_glossary_is_not_mutated(self) -> None:
        before = dict(DEFAULT_GLOSSARY)
        merge(DEFAULT_GLOSSARY, {"puerto": ("servlet",)})
        self.assertEqual(before, dict(DEFAULT_GLOSSARY))


if __name__ == "__main__":
    unittest.main()
