"""Auditoría determinista: las cinco comprobaciones que no necesitan ningún modelo."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docu.audit.verify import (
    WEIGHTS,
    AuditReport,
    Check,
    audit,
    check_citations,
    check_consistency,
    check_coverage,
    check_duplicates,
    check_freshness,
)
from docu.generate.facts import Fact

SOURCE = """def classify(stored, current):
    if stored != current:
        return "stale"
    return "fresh"
"""


def build_repo(root: Path) -> None:
    package = root / "src" / "demo"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "freshness.py").write_text(SOURCE, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["requests>=2"]\n', encoding="utf-8"
    )
    (root / "settings.yml").write_text("server:\n  port: 8080\n", encoding="utf-8")


def fact(kind: str, subject: str, citation: str, detail: str = "") -> Fact:
    return Fact(kind=kind, subject=subject, detail=detail, citation=citation)


class CitationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_repo(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_valid_citation_passes(self) -> None:
        facts = [fact("method", "freshness.classify", "src/demo/freshness.py#L1-L4")]
        self.assertEqual(check_citations(facts, self.root).failed, 0)

    def test_missing_file_fails(self) -> None:
        facts = [fact("method", "x.y", "src/demo/noexiste.py#L1-L2")]
        check = check_citations(facts, self.root)
        self.assertEqual(check.failed, 1)
        self.assertIn("inexistente", check.details[0])

    def test_range_out_of_file_fails(self) -> None:
        facts = [fact("method", "freshness.classify", "src/demo/freshness.py#L1-L99")]
        check = check_citations(facts, self.root)
        self.assertEqual(check.failed, 1)
        self.assertIn("fuera de", check.details[0])

    def test_subject_must_appear_in_span(self) -> None:
        facts = [fact("method", "freshness.otraCosa", "src/demo/freshness.py#L1-L2")]
        self.assertEqual(check_citations(facts, self.root).failed, 1)

    def test_route_any_only_requires_path(self) -> None:
        facts = [fact("route", "ANY /api/x", "src/demo/freshness.py#L1-L6")]
        # el path no está: falla
        self.assertEqual(check_citations(facts, self.root).failed, 1)

    def test_malformed_citation_fails(self) -> None:
        facts = [fact("type", "X", "sin-formato")]
        check = check_citations(facts, self.root)
        self.assertEqual(check.failed, 1)
        self.assertIn("formato", check.details[0])


class DuplicateTests(unittest.TestCase):
    def test_same_subject_different_citation_is_not_duplicate(self) -> None:
        facts = [
            fact("dependency", "vite", "package.json#L10-L10"),
            fact("dependency", "vite", "package.json#L30-L30"),
        ]
        self.assertEqual(check_duplicates(facts).failed, 0)

    def test_exact_repeat_is_duplicate(self) -> None:
        facts = [
            fact("dependency", "vite", "package.json#L10-L10"),
            fact("dependency", "vite", "package.json#L10-L10"),
        ]
        check = check_duplicates(facts)
        self.assertEqual(check.failed, 1)
        self.assertIn("vite", check.details[0])


class ConsistencyTests(unittest.TestCase):
    def test_missing_path_in_a_level_is_reported(self) -> None:
        docs = {
            "l1": "| GET | `/api/x` | `a.py#L1` |\n| GET | `/api/y` | `a.py#L2` |",
            "l3": "| Consultar | `/api/x` | `a.py#L1` |",
        }
        check = check_consistency(docs)
        self.assertEqual(check.failed, 1)
        self.assertIn("/api/y", check.details[0])

    def test_consistent_levels_pass(self) -> None:
        docs = {"l1": "| `/api/x` |", "l4": "| `/api/x` |"}
        self.assertEqual(check_consistency(docs).failed, 0)

    def test_single_level_is_not_compared(self) -> None:
        check = check_consistency({"l1": "| `/api/x` |"})
        self.assertEqual(check.total, 0)
        self.assertTrue(check.passed)


class CoverageTests(unittest.TestCase):
    def test_missing_section_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            facts = [fact("type", "X", "src/demo/freshness.py#L1-L2")]
            check = check_coverage(facts, root)
            self.assertGreater(check.failed, 0)

    def test_all_sections_present_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            facts = [
                fact("type", "X", "src/demo/freshness.py#L1-L2"),
                fact("dependency", "requests", "pyproject.toml#L3-L3"),
                fact("config_key", "server.port", "settings.yml#L2-L2"),
                fact("package", "demo", "src/demo/__init__.py#L1-L1"),
            ]
            self.assertEqual(check_coverage(facts, root).failed, 0)


class ScoreTests(unittest.TestCase):
    def test_all_passing_scores_100(self) -> None:
        report = AuditReport(project="x")
        for name in WEIGHTS:
            report.checks[name] = Check(name, total=10, failed=0)
        self.assertEqual(report.score, 100.0)
        self.assertTrue(report.passed)

    def test_failed_check_lowers_score_by_its_weight(self) -> None:
        report = AuditReport(project="x")
        for name in WEIGHTS:
            report.checks[name] = Check(name, total=10, failed=0)
        report.checks["citations"] = Check("citations", total=10, failed=10)
        self.assertAlmostEqual(report.score, 60.0, places=2)
        self.assertFalse(report.passed)

    def test_weighted_partial_failure(self) -> None:
        report = AuditReport(project="x")
        report.checks["duplicates"] = Check("duplicates", total=4, failed=1)
        self.assertAlmostEqual(report.score, 75.0, places=2)

    def test_report_serializes_and_renders(self) -> None:
        report = AuditReport(project="x")
        report.checks["citations"] = Check("citations", total=2, failed=1, details=("algo",))
        payload = report.to_dict()
        self.assertEqual(payload["project"], "x")
        self.assertIn("Auditoría", report.to_markdown())
        self.assertIn("algo", report.to_markdown())


class AuditIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_repo(self.root)
        self.docs = self.root / "docs" / "generated"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_audit_without_documents_still_runs(self) -> None:
        report = audit(self.root, self.docs)
        self.assertIn("citations", report.checks)
        # sin manifest, la frescura no puede pasar
        self.assertFalse(report.checks["freshness"].passed)

    def test_audit_after_generation_is_clean(self) -> None:
        from docu.generate.pipeline import generate

        generate(self.root, self.docs, project="demo")
        report = audit(self.root, self.docs)
        self.assertTrue(report.checks["citations"].passed)
        self.assertTrue(report.checks["freshness"].passed, msg=str(report.to_dict()))
        self.assertGreaterEqual(report.score, 99.0)

    def test_freshness_uses_same_discovery_as_generation(self) -> None:
        from docu.generate.pipeline import generate

        generate(self.root, self.docs, project="demo", exclude=["src/demo/freshness.py"])
        check = check_freshness(self.root, ("l1", "l4"), exclude=["src/demo/freshness.py"])
        self.assertTrue(check.passed, msg=str(check.to_dict()))


if __name__ == "__main__":
    unittest.main()
