"""Arnés de evaluación: tokenización, corpus, BM25 y aritmética de métricas."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from eval.harness import (
    BM25,
    Case,
    CaseResult,
    Expected,
    HybridIndex,
    Report,
    Segment,
    build_corpus,
    discover_files,
    evaluate,
    tokenize,
)
from eval.harness import _diversity, _looks_like_identifier, _overlaps


class TokenizeTests(unittest.TestCase):
    def test_camel_case_is_split(self) -> None:
        tokens = tokenize("BssSecurityConfig")
        self.assertIn("bss", tokens)
        self.assertIn("security", tokens)
        self.assertIn("config", tokens)

    def test_identifiers_with_separators_are_split(self) -> None:
        tokens = tokenize("bss.security.cache.enabled")
        for expected in ("bss", "security", "cache", "enabled"):
            self.assertIn(expected, tokens)

    def test_stopwords_are_removed(self) -> None:
        self.assertNotIn("de", tokenize("la configuración de la cadena"))
        self.assertIn("configuracion", tokenize("la configuración de la cadena"))

    def test_accents_are_folded(self) -> None:
        self.assertEqual(tokenize("configuración"), tokenize("configuracion"))
        self.assertIn("expiracion", tokenize("Expiración del token"))

    def test_accented_words_are_not_split(self) -> None:
        self.assertNotIn("n", tokenize("configuración"))

    def test_snake_case_and_numbers(self) -> None:
        tokens = tokenize("LEEWAY_SECONDS_60")
        self.assertIn("leeway", tokens)
        self.assertIn("seconds", tokens)
        self.assertIn("60", tokens)


class CorpusTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "Auth.java").write_text(
            "class Auth { void login() { tokenService.generate(); } }", encoding="utf-8"
        )
        (self.root / "README.md").write_text("# Proyecto\n", encoding="utf-8")
        (self.root / ".sdd").mkdir()
        (self.root / ".sdd" / "run.md").write_text("log de proceso SEGURIDAD", encoding="utf-8")
        (self.root / "target").mkdir()
        (self.root / "target" / "Gen.java").write_text("class Gen {}", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_process_artifacts_are_excluded(self) -> None:
        files = discover_files(self.root, ("*.java", "*.md"), (".sdd/*", "target/*"))
        self.assertIn("src/Auth.java", files)
        self.assertIn("README.md", files)
        self.assertNotIn(".sdd/run.md", files)
        self.assertNotIn("target/Gen.java", files)

    def test_build_corpus_produces_windows_with_path_prefix(self) -> None:
        segments = build_corpus(self.root, window=10, overlap=2)
        auth = [s for s in segments if s.path == "src/Auth.java"]
        self.assertEqual(len(auth), 1)
        self.assertEqual((auth[0].start, auth[0].end), (1, 1))
        # El path entra en los tokens: una consulta con el nombre del archivo debe acertar.
        self.assertIn("auth", auth[0].tokens)

    def test_empty_file_produces_no_segments(self) -> None:
        (self.root / "src" / "Empty.java").write_text("", encoding="utf-8")
        paths = {s.path for s in build_corpus(self.root)}
        self.assertNotIn("src/Empty.java", paths)


class BM25Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "Auth.java").write_text("class Auth { generateToken verifyExpiration }", encoding="utf-8")
        (root / "Cors.java").write_text("class Cors { allowedOrigins allowCredentials }", encoding="utf-8")
        (root / "Clean.java").write_text("class Clean { cleanup scheduled }", encoding="utf-8")
        self.index = BM25(segments=build_corpus(root, window=50, overlap=0))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_exact_term_wins(self) -> None:
        hits = self.index.search("allowedOrigins allowCredentials", k=1)
        self.assertEqual(hits[0][0].path, "Cors.java")

    def test_zero_score_results_are_dropped(self) -> None:
        self.assertEqual(self.index.search("inexistente_zzz", k=5), [])

    def test_k_limits_results(self) -> None:
        self.assertLessEqual(len(self.index.search("class", k=2)), 2)


class MetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "Jwt.java").write_text("class Jwt { clockSkewSeconds leeway }", encoding="utf-8")
        (root / "Cors.java").write_text("class Cors { allowedOrigins }", encoding="utf-8")
        self.index = BM25(segments=build_corpus(root, window=50, overlap=0))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _case(self, paths: list[str], lines: tuple[int, int] | None = None) -> Case:
        return Case(
            id="T-1",
            category="code",
            question="clockSkewSeconds leeway",
            expected=tuple(Expected(path=p, lines=lines) for p in paths),
        )

    def test_hit_and_mrr(self) -> None:
        result = evaluate([self._case(["Jwt.java"])], self.index, k=2)[0]
        self.assertTrue(result.hit)
        self.assertAlmostEqual(result.mrr, 1.0)
        self.assertAlmostEqual(result.recall, 1.0)

    def test_partial_recall_counts_only_required(self) -> None:
        case = Case(
            id="T-2",
            category="code",
            question="clockSkewSeconds leeway",
            expected=(
                Expected(path="Jwt.java"),
                Expected(path="Cors.java"),
            ),
        )
        result = evaluate([case], self.index, k=2)[0]
        self.assertAlmostEqual(result.recall, 0.5)  # solo Jwt es recuperable
        self.assertTrue(result.hit)

    def test_optional_expected_does_not_lower_recall(self) -> None:
        case = Case(
            id="T-3",
            category="code",
            question="clockSkewSeconds leeway",
            expected=(Expected(path="Jwt.java"), Expected(path="Cors.java", optional=True)),
        )
        result = evaluate([case], self.index, k=2)[0]
        self.assertAlmostEqual(result.recall, 1.0)

    def test_line_hit_requires_overlap(self) -> None:
        self.assertTrue(evaluate([self._case(["Jwt.java"], (1, 1))], self.index, k=2)[0].line_hit)
        self.assertFalse(evaluate([self._case(["Jwt.java"], (90, 99))], self.index, k=2)[0].line_hit)

    def test_no_required_paths_means_zero_recall(self) -> None:
        case = Case(id="T-4", category="code", question="x", expected=(Expected(path="A", optional=True),))
        self.assertEqual(evaluate([case], self.index, k=2)[0].recall, 0.0)


class OverlapTests(unittest.TestCase):
    def test_boundaries(self) -> None:
        self.assertTrue(_overlaps((10, 20), (20, 30)))
        self.assertTrue(_overlaps((10, 20), (5, 10)))
        self.assertFalse(_overlaps((10, 20), (21, 30)))
        self.assertFalse(_overlaps((10, 20), (1, 9)))


class QueryRoutingTests(unittest.TestCase):
    def test_code_shapes_are_identifiers(self) -> None:
        for query in (
            "SecurityErrorWriter json error",
            "bss.security.cache.enabled",
            "LEEWAY_SECONDS 60",
            "application.yml server port",
            "@PostMapping /api/auth/refresh",
            "spring-boot-starter-parent",
        ):
            with self.subTest(query=query):
                self.assertTrue(_looks_like_identifier(query))

    def test_human_questions_are_not_identifiers(self) -> None:
        for query in (
            "¿Dónde se define la cadena de filtros de seguridad?",
            "¿Qué versiones de Spring Boot, Spring Security y jjwt fija el proyecto?",
            "¿Cómo se restringe CORS y qué configuración es insegura?",
        ):
            with self.subTest(query=query):
                self.assertFalse(_looks_like_identifier(query))

    def test_capitalised_product_names_do_not_trigger_routing(self) -> None:
        # Leccion medida: "Spring Boot" o "CORS" enrutados al indice de simbolos bajaban el MRR.
        self.assertFalse(_looks_like_identifier("Spring Boot y CORS"))


class DiversityTests(unittest.TestCase):
    def _segments(self) -> list[Segment]:
        return [
            Segment(path="A.java", start=index, end=index + 1, text="", tokens=())
            for index in range(1, 6)
        ] + [Segment(path="B.java", start=1, end=2, text="", tokens=())]

    def test_cap_limits_chunks_per_file(self) -> None:
        segments = self._segments()
        ordered = [((s.path, s.start, s.end), 1.0 - index * 0.01) for index, s in enumerate(segments)]
        by_key = {(s.path, s.start, s.end): s for s in segments}
        selected = _diversity(ordered, k=6, cap=2, by_key=by_key)
        paths = [by_key[key].path for key, _score in selected]
        self.assertEqual(paths.count("A.java"), 2)
        self.assertIn("B.java", paths)

    def test_selection_stops_at_k(self) -> None:
        segments = self._segments()
        ordered = [((s.path, s.start, s.end), 1.0) for s in segments]
        by_key = {(s.path, s.start, s.end): s for s in segments}
        self.assertEqual(len(_diversity(ordered, k=3, cap=5, by_key=by_key)), 3)


class ReportTests(unittest.TestCase):
    def _result(self, recall: float, hit: bool, mrr: float) -> CaseResult:
        return CaseResult("C", "code", recall, hit, mrr, None, (), 1.0)

    def test_aggregates(self) -> None:
        report = Report(
            project="demo",
            k=10,
            files=2,
            segments=3,
            results=[self._result(1.0, True, 1.0), self._result(0.0, False, 0.0)],
        )
        overall = report.overall
        self.assertAlmostEqual(overall["recall"], 0.5)
        self.assertAlmostEqual(overall["hit_rate"], 0.5)
        self.assertAlmostEqual(overall["mrr"], 0.5)

    def test_serialisation_and_markdown(self) -> None:
        report = Report(
            project="demo", k=10, files=2, segments=3, results=[self._result(1.0, True, 1.0)], query_field="query"
        )
        payload = report.to_dict()
        self.assertEqual(payload["query_field"], "query")
        self.assertIn("recall@10", report.to_markdown())


if __name__ == "__main__":
    unittest.main()
