"""Prosa delegada al agente: docu no llama a un modelo, valida lo que el agente devuelve."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from docu.generate.facts import Fact
from docu.generate.prose import (
    MAX_SENTENCES,
    MIN_JUDGE_SCORE,
    build_judge_request,
    build_request,
    fact_id,
    load,
    load_verdict,
    render,
    save,
    validate,
)

FACTS = [
    Fact("type", "Pedido", "class", "src/Pedido.java#L3-L20"),
    Fact("field", "Pedido.total", "BigDecimal", "src/Pedido.java#L7-L7"),
    Fact("route", "POST /api/pedidos", "PedidoController.crear", "src/PedidoController.java#L40-L48"),
    Fact("intent", "Pedido", "Representa un pedido con su total.", "README.md#L12-L14"),
    Fact("decision", "Usar cola de eventos", "Accepted · por latencia", "docs/adr/1.md#L1-L6"),
]


def sentence(text: str, *ids: str) -> dict[str, object]:
    return {"text": text, "fact_ids": list(ids)}


class RequestTests(unittest.TestCase):
    def test_request_offers_citable_facts_only(self) -> None:
        request = build_request("demo", FACTS)
        ids = {fact["id"] for fact in request["facts"]}  # type: ignore[index]
        self.assertIn("type:Pedido", ids)
        self.assertIn("intent:Pedido", ids)
        self.assertEqual(request["rules"]["must_reference_fact_ids"], True)  # type: ignore[index]

    def test_request_markdown_is_pasteable(self) -> None:
        from docu.generate.prose import render_request_markdown

        text = render_request_markdown(build_request("demo", FACTS))
        self.assertIn("## Hechos disponibles", text)
        self.assertIn("type:Pedido", text)
        self.assertIn("prose-response.json", text)


class ValidationTests(unittest.TestCase):
    def test_valid_response_is_accepted(self) -> None:
        response, index = validate(
            {
                "reviewer": "agente",
                "sections": {
                    "intro": [
                        sentence("El pedido se expone con la ruta POST /api/pedidos.", "route:POST /api/pedidos"),
                        sentence("Representa un pedido con su total.", "intent:Pedido"),
                    ]
                },
            },
            FACTS,
        )
        self.assertTrue(response.accepted, msg=response.errors)
        self.assertEqual(len(response.sections["intro"]), 2)
        self.assertIn("type:Pedido", index)

    def test_unknown_fact_is_rejected(self) -> None:
        response, _index = validate(
            {"sections": {"intro": [sentence("Usa Chroma para vectores.", "type:Chroma")]}}, FACTS
        )
        self.assertFalse(response.accepted)
        self.assertIn("inexistentes", response.errors[0])

    def test_invented_number_is_rejected(self) -> None:
        """La regla que impide el «98,7 %» inventado."""
        response, _index = validate(
            {
                "sections": {
                    "intro": [sentence("Cubre el 98,7 % de los módulos.", "type:Pedido")]
                }
            },
            FACTS,
        )
        self.assertFalse(response.accepted)
        self.assertIn("cifras sin evidencia", response.errors[0])
        self.assertIn("98.7", response.errors[0])

    def test_number_present_in_cited_fact_is_allowed(self) -> None:
        response, _index = validate(
            {
                "sections": {
                    "intro": [sentence("La ruta POST /api/pedidos atiende el alta.", "route:POST /api/pedidos")]
                }
            },
            FACTS,
        )
        self.assertTrue(response.accepted, msg=response.errors)

    def test_version_prefix_is_supported(self) -> None:
        """F-21: «React 19» debe aceptarse si el hecho dice ^19.0.1."""
        facts = [Fact("dependency", "react", "^19.0.1", "package.json#L30-L30")]
        response, _index = validate(
            {"sections": {"intro": [sentence("Se construye con React 19 y Vite.", "dependency:react")]}},
            facts,
        )
        self.assertTrue(response.accepted, msg=response.errors)

    def test_number_with_trailing_comma_is_supported(self) -> None:
        facts = [Fact("dependency", "vite", "^6.2.3", "package.json#L31-L31")]
        response, _index = validate(
            {"sections": {"intro": [sentence("Usa Vite 6, un bundler rápido.", "dependency:vite")]}},
            facts,
        )
        self.assertTrue(response.accepted, msg=response.errors)

    def test_headings_are_rejected(self) -> None:
        response, _index = validate(
            {"sections": {"intro": [sentence("## Introducción\n\nTexto.", "type:Pedido")]}}, FACTS
        )
        self.assertFalse(response.accepted)
        self.assertTrue(any("encabezados" in error for error in response.errors))

    def test_too_many_sentences_are_rejected(self) -> None:
        payload = {
            "sections": {
                "intro": [sentence("Una frase más sobre el pedido.", "type:Pedido")] * (MAX_SENTENCES + 1)
            }
        }
        response, _index = validate(payload, FACTS)
        self.assertFalse(response.accepted)
        self.assertTrue(any("máximo" in error for error in response.errors))

    def test_sentence_without_facts_is_a_warning(self) -> None:
        response, _index = validate(
            {"sections": {"intro": [sentence("Este proyecto existe.", )]}}, FACTS
        )
        self.assertTrue(response.accepted)
        self.assertTrue(any("derivada" in warning for warning in response.warnings))

    def test_empty_response_is_rejected(self) -> None:
        response, _index = validate({"sections": {}}, FACTS)
        self.assertFalse(response.accepted)


class JudgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.response, self.index = validate(
            {
                "reviewer": "agente",
                "sections": {"intro": [sentence("Representa un pedido con su total.", "intent:Pedido")]},
            },
            FACTS,
        )

    def test_request_includes_rubric_and_cited_facts(self) -> None:
        request = build_judge_request("demo", self.response, FACTS, self.index)
        self.assertIn("fidelidad", request["criteria"])  # type: ignore[index]
        self.assertIn("intent:Pedido", request["cited_facts"])  # type: ignore[index]
        self.assertEqual(request["threshold"], MIN_JUDGE_SCORE)

    def test_verdict_above_threshold_is_accepted(self) -> None:
        verdict = load_verdict({"judge": "juez", "score": 4.2, "criteria": {"fidelidad": 5}})
        self.assertTrue(verdict.accepted)
        self.assertEqual(verdict.criteria["fidelidad"], 5.0)

    def test_verdict_below_threshold_is_not_accepted(self) -> None:
        verdict = load_verdict({"judge": "juez", "score": 2.0})
        self.assertFalse(verdict.accepted)

    def test_invalid_verdict_is_reported(self) -> None:
        self.assertTrue(load_verdict({"score": "muy bueno"}).errors)
        self.assertTrue(load_verdict({"score": 9}).errors)
        self.assertTrue(load_verdict({}).errors)


class PurposeTests(unittest.TestCase):
    def test_purpose_facts_come_first(self) -> None:
        """F-23: sin hechos de propósito la intro sólo puede enumerar tecnología."""
        request = build_request("demo", FACTS)
        kinds = [fact["kind"] for fact in request["facts"]]  # type: ignore[index]
        self.assertEqual(kinds[0], "intent")
        self.assertEqual(request["has_purpose_facts"], True)  # type: ignore[index]

    def test_request_warns_without_purpose(self) -> None:
        request = build_request("demo", [FACTS[0]])
        self.assertFalse(request["has_purpose_facts"])  # type: ignore[index]
        self.assertIn("propósito", str(request.get("warning")))


class RenderAndStoreTests(unittest.TestCase):
    def test_render_cites_every_sentence(self) -> None:
        response, index = validate(
            {
                "reviewer": "agente",
                "sections": {"intro": [sentence("Representa un pedido con su total.", "intent:Pedido")]},
            },
            FACTS,
        )
        markdown = render(response, index)
        self.assertIn("Prosa redactada por `agente`", markdown)
        self.assertIn("README.md#L12-L14", markdown)
        self.assertIn("ninguna frase aporta datos nuevos", markdown)

    def test_roundtrip_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response, index = validate(
                {
                    "reviewer": "agente",
                    "sections": {"intro": [sentence("Representa un pedido con su total.", "intent:Pedido")]},
                },
                FACTS,
            )
            verdict = load_verdict({"judge": "juez", "score": 4.0})
            path = save(tmp, response, verdict)
            self.assertTrue(path.is_file())
            stored = load(tmp)
            self.assertIsNotNone(stored)
            prose, stored_verdict = stored  # type: ignore[misc]
            self.assertEqual(prose.reviewer, "agente")
            self.assertEqual(stored_verdict.score, 4.0)
            self.assertIn("README.md#L12-L14", render(prose, index))

    def test_load_without_store_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load(tmp))

    def test_store_is_json_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response, _index = validate(
                {"reviewer": "agente", "sections": {"intro": [sentence("Texto.", "type:Pedido")]}}, FACTS
            )
            path = save(tmp, response)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reviewer"], "agente")


class PipelineTests(unittest.TestCase):
    def test_accepted_prose_appears_in_the_document_with_provenance(self) -> None:
        from docu.delivery.cli import main
        from docu.generate.facts import Fact as F

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "demo.py").write_text(
                '"""Módulo de ejemplo que explica su intención."""\n\n\nclass Demo:\n    valor: int = 1\n',
                encoding="utf-8",
            )
            (root / ".docu").mkdir()
            response = {
                "reviewer": "agente-de-prueba",
                "sections": {
                    "intro": [
                        {"text": "El módulo de ejemplo declara su intención.", "fact_ids": ["intent:src/demo.py (módulo)"]}
                    ]
                },
            }
            (root / ".docu" / "prose.json").write_text(
                json.dumps({"reviewer": "agente-de-prueba", "sections": response["sections"], "verdict": None}),
                encoding="utf-8",
            )
            code = main(["gen", "--root", str(root), "--out", str(root / "docs" / "generated"), "--level", "l1"])
            self.assertEqual(code, 0)
            document = (root / "docs" / "generated" / "l1-manual-tecnico.md").read_text(encoding="utf-8")
            self.assertIn("El módulo de ejemplo declara su intención.", document)
            self.assertIn("redactor: `agente-de-prueba`", document)


if __name__ == "__main__":
    unittest.main()
