"""Chunker sintactico: un simbolo por chunk, prefijo obligatorio y corte sin perdida."""

from __future__ import annotations

import unittest

from docu.adapters.langs.java import JavaLangAdapter
from docu.core.contracts import Artifact, SourceKind, SymbolKind, utcnow
from docu.index.chunker import SymbolChunker, estimate_tokens

SOURCE = '''package com.example.demo;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1")
public class DemoController {

    private final String name = "demo";

    @GetMapping("/items")
    public List<String> listItems() {
        return List.of("a", "b");
    }

    @PostMapping("/items")
    public void createItem(String value) {
        store(value);
    }

    private void store(String value) {
        this.last = value;
    }
}
'''

LONG_METHOD = (
    "public class Big {\n    public void big() {\n"
    + "".join(f"        int value{i} = {i};\n" for i in range(80))
    + "    }\n}\n"
)


def artifact(path: str = "DemoController.java") -> Artifact:
    return Artifact(
        artifact_id=f"git:demo@abc:{path}",
        kind=SourceKind.GIT_REPOSITORY,
        uri=f"backend-security-core/src/main/java/{path}",
        content_hash="sha256:seed",
        captured_at=utcnow(),
        lang="java",
    )


class ChunkingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = JavaLangAdapter()
        self.chunker = SymbolChunker()
        self.art = artifact()
        self.symbols = self.adapter.symbols(self.art.uri, SOURCE)
        self.chunks = self.chunker.chunk(self.art, self.symbols, SOURCE)

    def test_one_chunk_per_method_plus_container_shell(self) -> None:
        symbols = [c.enclosing_symbol for c in self.chunks]
        self.assertIn("DemoController", symbols)          # cascara del tipo
        self.assertIn("DemoController.listItems", symbols)
        self.assertIn("DemoController.createItem", symbols)
        self.assertIn("DemoController.store", symbols)
        self.assertEqual(len(self.chunks), 4)

    def test_container_shell_excludes_method_bodies(self) -> None:
        shell = next(c for c in self.chunks if c.enclosing_symbol == "DemoController")
        self.assertIn("private final String name", shell.content)
        self.assertNotIn("List.of", shell.content)
        self.assertNotIn("public void createItem", shell.content)

    def test_method_chunk_contains_its_annotation(self) -> None:
        chunk = next(c for c in self.chunks if c.enclosing_symbol == "DemoController.listItems")
        self.assertIn("@GetMapping", chunk.content)

    def test_prefix_carries_file_type_symbol_and_route(self) -> None:
        chunk = next(c for c in self.chunks if c.enclosing_symbol == "DemoController.createItem")
        self.assertIn(f"File: {self.art.uri}", chunk.content_prefix)
        self.assertIn("Type: DemoController", chunk.content_prefix)
        self.assertIn("Symbol: DemoController.createItem", chunk.content_prefix)
        self.assertIn("Route: POST /api/v1/items", chunk.content_prefix)
        self.assertIn("Annotations: @PostMapping", chunk.content_prefix)

    def test_container_prefix_names_the_type(self) -> None:
        shell = next(c for c in self.chunks if c.enclosing_symbol == "DemoController")
        self.assertIn("Type: class DemoController", shell.content_prefix)

    def test_routes_are_not_duplicated_as_chunks(self) -> None:
        route_chunks = [c for c in self.chunks if c.symbol_kind is SymbolKind.HTTP_ROUTE]
        self.assertEqual(route_chunks, [])

    def test_chunk_ids_are_unique(self) -> None:
        ids = [c.chunk_id for c in self.chunks]
        self.assertEqual(len(ids), len(set(ids)))

    def test_line_ranges_are_within_file(self) -> None:
        total = SOURCE.count("\n") + 1
        for chunk in self.chunks:
            self.assertGreaterEqual(chunk.line_start, 1)
            self.assertLessEqual(chunk.line_end, total)
            self.assertLessEqual(chunk.line_start, chunk.line_end)

    def test_content_hash_changes_with_content(self) -> None:
        modified = SOURCE.replace('List.of("a", "b")', 'List.of("a", "b", "c")')
        symbols = self.adapter.symbols(self.art.uri, modified)
        chunks = self.chunker.chunk(self.art, symbols, modified)
        before = next(c for c in self.chunks if c.enclosing_symbol == "DemoController.listItems")
        after = next(c for c in chunks if c.enclosing_symbol == "DemoController.listItems")
        self.assertNotEqual(before.content_hash, after.content_hash)
        self.assertNotEqual(before.content_hash, after.content_hash)  # estable al comparar

    def test_chunking_is_deterministic(self) -> None:
        again = self.chunker.chunk(self.art, self.symbols, SOURCE)
        self.assertEqual([c.content_hash for c in self.chunks], [c.content_hash for c in again])

    def test_empty_source_yields_no_chunks(self) -> None:
        self.assertEqual(self.chunker.chunk(self.art, (), ""), ())


class SplittingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = JavaLangAdapter()
        self.chunker = SymbolChunker(max_tokens=60, overlap_tokens=8)
        self.art = artifact("Big.java")
        self.symbols = self.adapter.symbols(self.art.uri, LONG_METHOD)
        self.chunks = self.chunker.chunk(self.art, self.symbols, LONG_METHOD)
        self.method_chunks = [c for c in self.chunks if c.enclosing_symbol == "Big.big"]

    def test_class_shell_is_also_chunked(self) -> None:
        shells = [c for c in self.chunks if c.enclosing_symbol == "Big"]
        self.assertEqual(len(shells), 1)
        self.assertNotIn("int value0", shells[0].content)

    def test_oversized_symbol_is_split_into_parts(self) -> None:
        self.assertGreater(len(self.method_chunks), 1)
        self.assertTrue(all(":part" in c.chunk_id for c in self.method_chunks))
        self.assertTrue(all(" part " in c.content_prefix for c in self.method_chunks))

    def test_parts_are_numbered_sequentially(self) -> None:
        parts = [c.chunk_id.rsplit(":part", 1)[1] for c in self.method_chunks]
        self.assertEqual(parts, [str(i) for i in range(1, len(parts) + 1)])

    def test_no_part_exceeds_the_budget(self) -> None:
        for chunk in self.method_chunks:
            self.assertLessEqual(estimate_tokens(chunk.content), self.chunker.max_tokens)

    def test_all_content_is_covered(self) -> None:
        joined = "".join(chunk.content for chunk in self.method_chunks)
        for index in range(0, 80, 7):
            self.assertIn(f"int value{index} = {index};", joined)

    def test_small_symbol_stays_whole(self) -> None:
        chunks = SymbolChunker(max_tokens=100_000).chunk(self.art, self.symbols, LONG_METHOD)
        self.assertEqual(len(chunks), 2)  # cascara + metodo
        self.assertFalse(any(":part" in c.chunk_id for c in chunks))


class EstimateTests(unittest.TestCase):
    def test_estimate_is_at_least_one(self) -> None:
        self.assertEqual(estimate_tokens(""), 1)
        self.assertEqual(estimate_tokens("abcd"), 1)
        self.assertEqual(estimate_tokens("a" * 40), 10)


if __name__ == "__main__":
    unittest.main()
