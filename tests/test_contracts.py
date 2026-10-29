"""Contratos: las invariantes del producto son las que impiden publicar basura."""

from __future__ import annotations

import json
import unittest
from datetime import timedelta

from docu.core.contracts import (
    Artifact,
    Chunk,
    Claim,
    ContentNode,
    DocState,
    Metrics,
    Mode,
    RunRecord,
    SourceKind,
    SymbolKind,
    utcnow,
)


def _chunk(**overrides: object) -> Chunk:
    base = dict(
        chunk_id="git:acme/x@abc:src/A.java#A.run",
        artifact_id="art-1",
        source_type=SourceKind.GIT_REPOSITORY,
        content="void run() {}",
        content_prefix="[File: src/A.java | Class: A | Method: run | lines 10-12]",
        content_hash="sha256:00",
        file_path="src/A.java",
        lang="java",
        enclosing_symbol="A.run",
        symbol_kind=SymbolKind.METHOD,
        line_start=10,
        line_end=12,
        ingested_at=utcnow(),
    )
    base.update(overrides)
    return Chunk(**base)  # type: ignore[arg-type]


class ArtifactTests(unittest.TestCase):
    def test_volatile_source_without_snapshot_is_not_citable(self) -> None:
        with self.assertRaises(ValueError):
            Artifact(
                artifact_id="web-1",
                kind=SourceKind.WEB,
                uri="https://docs.spring.io/x",
                content_hash="sha256:11",
                captured_at=utcnow(),
            )

    def test_volatile_source_with_snapshot_is_accepted(self) -> None:
        artifact = Artifact(
            artifact_id="web-1",
            kind=SourceKind.WEB,
            uri="https://docs.spring.io/x",
            content_hash="sha256:11",
            captured_at=utcnow(),
            snapshot_path=".docu/snapshots/web-1.html",
        )
        self.assertEqual(artifact.kind, SourceKind.WEB)


class ChunkTests(unittest.TestCase):
    def test_prefix_is_mandatory(self) -> None:
        with self.assertRaises(ValueError):
            _chunk(content_prefix="")

    def test_line_range_is_validated(self) -> None:
        with self.assertRaises(ValueError):
            _chunk(line_start=20, line_end=10)

    def test_citation_is_human_readable(self) -> None:
        self.assertEqual(_chunk().citation, "src/A.java#L10-L12")

    def test_record_is_flat_and_json_safe(self) -> None:
        record = _chunk().to_record()
        self.assertEqual(record["citation"], "src/A.java#L10-L12")
        json.dumps(record)


class ClaimAndNodeTests(unittest.TestCase):
    def test_claim_without_evidence_is_unverified(self) -> None:
        self.assertFalse(Claim("expone puerto 8080").verified)
        self.assertTrue(Claim("expone puerto 8080", ("chunk-1",)).verified)

    def test_node_with_unsupported_claim_is_not_publishable(self) -> None:
        node = ContentNode(node_id="n1", kind="api", title="API")
        node.claims.append(Claim("usa JWT", ()))
        self.assertEqual(len(node.unsupported), 1)
        self.assertFalse(node.is_publishable())

    def test_node_with_full_evidence_is_publishable(self) -> None:
        node = ContentNode(node_id="n1", kind="api", title="API")
        node.claims.append(Claim("usa JWT", ("chunk-1",)))
        self.assertTrue(node.is_publishable())

    def test_stale_node_is_not_publishable(self) -> None:
        node = ContentNode(node_id="n1", kind="api", title="API", state=DocState.STALE)
        self.assertFalse(node.is_publishable())


class RunRecordTests(unittest.TestCase):
    def test_jsonl_line_roundtrip(self) -> None:
        record = RunRecord(
            run_id="r1",
            project="demo",
            commit="abc123",
            mode=Mode.APPLY,
            started_at=utcnow(),
            versions={"docu": "0.1.0", "chunker": "ast-v2"},
        )
        payload = json.loads(record.to_jsonl())
        self.assertEqual(payload["mode"], "apply")
        self.assertEqual(payload["versions"]["chunker"], "ast-v2")
        self.assertIsNone(payload["metrics"])

    def test_duration_requires_finish(self) -> None:
        start = utcnow()
        record = RunRecord(run_id="r2", project="demo", commit=None, mode=Mode.PROPOSE, started_at=start)
        self.assertIsNone(record.duration_s)
        record.finished_at = start + timedelta(seconds=42)
        self.assertEqual(record.duration_s, 42.0)


if __name__ == "__main__":
    unittest.main()
