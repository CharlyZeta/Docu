"""Frescura: el hash de seis componentes y la idempotencia son la base del mantenimiento incremental."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from docu.core.contracts import DocState, FreshnessRecord, utcnow
from docu.index.freshness import (
    HASH_COMPONENTS,
    InputComponents,
    classify,
    compute_input_hash,
    is_idempotent,
    transition,
)


def _components(**overrides: str) -> InputComponents:
    base = dict(
        source_content="sha256:a",
        deps_signature="sha256:b",
        template="l1-reference@v1",
        embedder="onnx-bge-768@1",
        chunker="ast-v2",
        profile="sha256:c",
    )
    base.update(overrides)
    return InputComponents(**base)  # type: ignore[arg-type]


class InputHashTests(unittest.TestCase):
    def test_six_components_are_tracked(self) -> None:
        self.assertEqual(
            HASH_COMPONENTS,
            ("source_content", "deps_signature", "template", "embedder", "chunker", "profile"),
        )

    def test_hash_is_stable(self) -> None:
        self.assertEqual(compute_input_hash(_components()), compute_input_hash(_components()))

    def test_hash_is_prefixed(self) -> None:
        self.assertTrue(compute_input_hash(_components()).startswith("sha256:"))

    def test_embedder_upgrade_changes_hash(self) -> None:
        base = compute_input_hash(_components())
        self.assertNotEqual(base, compute_input_hash(_components(embedder="onnx-bge-768@2")))
        self.assertNotEqual(base, compute_input_hash(_components(chunker="ast-v3")))

    def test_empty_component_is_a_bug(self) -> None:
        with self.assertRaises(ValueError):
            compute_input_hash(_components(template=""))


class ClassifyTests(unittest.TestCase):
    def test_never_generated_is_stale(self) -> None:
        self.assertIs(classify(stored_hash=None, current_hash="h", generated_at=None), DocState.STALE)

    def test_missing_timestamp_is_stale(self) -> None:
        self.assertIs(classify(stored_hash="h", current_hash="h", generated_at=None), DocState.STALE)

    def test_hash_mismatch_is_stale(self) -> None:
        state = classify(stored_hash="old", current_hash="new", generated_at=utcnow())
        self.assertIs(state, DocState.STALE)

    def test_within_ttl_is_fresh(self) -> None:
        state = classify(stored_hash="h", current_hash="h", generated_at=utcnow(), ttl_days=90)
        self.assertIs(state, DocState.FRESH)

    def test_past_ttl_is_expired(self) -> None:
        old = utcnow() - timedelta(days=120)
        state = classify(stored_hash="h", current_hash="h", generated_at=old, ttl_days=90)
        self.assertIs(state, DocState.EXPIRED)


class TransitionTests(unittest.TestCase):
    def test_first_run_has_no_regression(self) -> None:
        result = transition(node_id="n1", record=None, current_hash="h1")
        self.assertIs(result.state, DocState.STALE)

    def test_unchanged_input_keeps_fresh(self) -> None:
        now = utcnow()
        record = FreshnessRecord(node_id="n1", input_hash="h1", state=DocState.FRESH, generated_at=now)
        result = transition(node_id="n1", record=record, current_hash="h1", now=now)
        self.assertIs(result.state, DocState.FRESH)

    def test_changed_neighbour_marks_stale(self) -> None:
        now = utcnow()
        record = FreshnessRecord(node_id="n1", input_hash="h1", state=DocState.FRESH, generated_at=now)
        result = transition(node_id="n1", record=record, current_hash="h2", now=now)
        self.assertIs(result.state, DocState.STALE)
        self.assertEqual(result.input_hash, "h2")

    def test_transition_does_not_mutate_previous(self) -> None:
        now = utcnow()
        record = FreshnessRecord(node_id="n1", input_hash="h1", state=DocState.FRESH, generated_at=now)
        copy = replace(record)
        transition(node_id="n1", record=record, current_hash="h2", now=now)
        self.assertEqual(record, copy)


class IdempotencyTests(unittest.TestCase):
    def test_same_commit_is_idempotent(self) -> None:
        self.assertTrue(is_idempotent(previous_hash="h", current_hash="h"))

    def test_new_commit_is_not(self) -> None:
        self.assertFalse(is_idempotent(previous_hash="h", current_hash="i"))

    def test_no_previous_hash_is_not(self) -> None:
        self.assertFalse(is_idempotent(previous_hash=None, current_hash="h"))


if __name__ == "__main__":
    unittest.main()
