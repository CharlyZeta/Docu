"""Recuperación híbrida sobre código: canales, fusión y degradación sin modelo."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docu.retrieve.hybrid import CodeChunk, build_chunks, build_index

FRESHNESS = '''from __future__ import annotations

from dataclasses import dataclass

DEFAULT_TTL_DAYS = 90


@dataclass(frozen=True)
class FreshnessRecord:
    node_id: str
    ttl_days: int = DEFAULT_TTL_DAYS


def classify(stored_hash: str | None, current_hash: str, ttl_days: int = DEFAULT_TTL_DAYS) -> str:
    """Decide si una página está desactualizada comparando hashes y TTL."""
    if stored_hash is None:
        return "stale"
    if stored_hash != current_hash:
        return "stale"
    return "fresh"


def transition(record: FreshnessRecord | None, current_hash: str) -> FreshnessRecord:
    return FreshnessRecord(node_id="x", ttl_days=record.ttl_days if record else 90)
'''

MANIFEST = '''from dataclasses import dataclass


@dataclass
class Manifest:
    project: str = ""


def state_of(entry: object | None, current_hash: str) -> str:
    """Estado de la página: sin manifest es stale."""
    if entry is None:
        return "stale"
    return "fresh"
'''


def build_repo(root: Path) -> None:
    package = root / "src" / "demo"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "freshness.py").write_text(FRESHNESS, encoding="utf-8")
    (package / "manifest.py").write_text(MANIFEST, encoding="utf-8")


class BuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_repo(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_chunks_carry_citations_and_symbols(self) -> None:
        chunks = build_chunks(self.root)
        self.assertTrue(chunks)
        self.assertTrue(all("#L" in chunk.citation for chunk in chunks))
        symbols = {chunk.symbol for chunk in chunks if chunk.symbol}
        self.assertIn("classify", symbols)

    def test_tests_are_excluded_by_default(self) -> None:
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_fresh.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        chunks = build_chunks(self.root)
        self.assertFalse(any(chunk.path.startswith("tests/") for chunk in chunks))

    def test_include_tests_flag(self) -> None:
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_fresh.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        chunks = build_chunks(self.root, include_tests=True)
        self.assertTrue(any(chunk.path.startswith("tests/") for chunk in chunks))

    def test_exclusions_are_respected(self) -> None:
        chunks = build_chunks(self.root, exclude=["src/demo/manifest.py"])
        self.assertFalse(any(chunk.path.endswith("manifest.py") for chunk in chunks))

    def test_empty_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(build_chunks(Path(tmp)), [])


class SearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_repo(self.root)
        self.index = build_index(self.root, dense=False)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_capabilities_declare_missing_dense_channel(self) -> None:
        capabilities = self.index.capabilities()
        self.assertFalse(capabilities["dense"])
        self.assertEqual(capabilities["channels"], ["lexical", "symbol"])

    def test_natural_question_finds_the_right_function(self) -> None:
        hits = self.index.search("decide si una página está desactualizada")
        self.assertTrue(hits)
        paths = [chunk.path for chunk, _score in hits]
        self.assertIn("src/demo/freshness.py", paths)
        self.assertEqual(hits[0][0].symbol, "classify")

    def test_identifier_query_hits_the_exact_symbol(self) -> None:
        hits = self.index.search("state_of")
        self.assertEqual(hits[0][0].symbol, "state_of")

    def test_dotted_identifier_hits_the_exact_symbol(self) -> None:
        hits = self.index.search("demo.freshness.classify")
        self.assertEqual(hits[0][0].symbol, "classify")

    def test_unknown_term_returns_nothing(self) -> None:
        self.assertEqual(self.index.search("ornitorrinco zzz"), [])

    def test_glossary_improves_domain_vocabulary(self) -> None:
        index = build_index(
            self.root,
            dense=False,
            glossary={"desactualizada": ("stale", "classify")},
        )
        hits = index.search("página desactualizada")
        self.assertEqual(hits[0][0].symbol, "classify")

    def test_diversity_cap_limits_chunks_per_file(self) -> None:
        hits = self.index.search("hash", limit=10)
        per_file: dict[str, int] = {}
        for chunk, _score in hits:
            per_file[chunk.path] = per_file.get(chunk.path, 0) + 1
        self.assertTrue(all(count <= 2 for count in per_file.values()))

    def test_limit_is_respected(self) -> None:
        self.assertLessEqual(len(self.index.search("hash page stale", limit=2)), 2)

    def test_empty_index_search(self) -> None:
        self.assertEqual(build_index(self.root / "nada", dense=False).search("x"), [])


class ChunkSerializationTests(unittest.TestCase):
    def test_to_dict_is_json_ready(self) -> None:
        chunk = CodeChunk(path="a.py", start=1, end=2, text="def f(): ...", symbol="f", kind="function")
        payload = chunk.to_dict(0.5)
        self.assertEqual(payload["citation"], "a.py#L1-L2")
        self.assertEqual(payload["score"], 0.5)
        self.assertIn("excerpt", payload)


if __name__ == "__main__":
    unittest.main()
