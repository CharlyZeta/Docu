"""Frescura e integración continua: la documentación que no se convierte en carga."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from docu.core.contracts import DocState, sha256_of, utcnow
from docu.delivery.cli import main
from docu.delivery.exit_codes import ExitCode
from docu.generate.pipeline import generate, inspect
from docu.index.manifest import (
    DocEntry,
    Manifest,
    fact_signature,
    input_hash_for,
    state_of,
)

JAVA = '''@RestController
@RequestMapping("/api")
public class Api {
    @GetMapping("/ping")
    public String ping() { return "pong"; }
}
'''


def build_repo(root: Path) -> None:
    """Fixture con las cinco categorias de hechos: la compuerta debe poder aprobarla."""
    (root / "src" / "main" / "java").mkdir(parents=True)
    (root / "src" / "main" / "java" / "Api.java").write_text(JAVA, encoding="utf-8")
    (root / "src" / "main" / "resources").mkdir(parents=True)
    (root / "src" / "main" / "resources" / "application.yml").write_text(
        "server:\n  port: 8080\n", encoding="utf-8"
    )
    (root / "pom.xml").write_text(
        "<project><modules><module>core</module></modules>"
        "<dependencies><dependency><groupId>g</groupId><artifactId>a</artifactId>"
        "<version>1.0</version></dependency></dependencies></project>",
        encoding="utf-8",
    )


def run_cli(*argv: str) -> tuple[int, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        code = main(list(argv))
    return code, buffer.getvalue()


class ManifestTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        manifest = Manifest(
            project="demo",
            docs=[
                DocEntry(
                    level="l1",
                    path="docs/l1.md",
                    input_hash="sha256:aaa",
                    generated_at=utcnow().isoformat(),
                    content_hash="sha256:bbb",
                    sources={"a.java": "123"},
                )
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = manifest.save(Path(tmp) / "manifest.json")
            restored = Manifest.load(path)
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored.project, "demo")
        self.assertEqual(restored.entry("l1").input_hash, "sha256:aaa")  # type: ignore[union-attr]

    def test_missing_manifest_returns_none(self) -> None:
        self.assertIsNone(Manifest.load(Path("no-existe.json")))

    def test_corrupt_manifest_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text("{ no es json", encoding="utf-8")
            self.assertIsNone(Manifest.load(path))

    def test_upsert_replaces_level(self) -> None:
        manifest = Manifest(project="demo")
        entry = DocEntry("l1", "a.md", "h1", utcnow().isoformat(), "c1")
        manifest.upsert(entry)
        manifest.upsert(DocEntry("l1", "b.md", "h2", utcnow().isoformat(), "c2"))
        self.assertEqual(len(manifest.docs), 1)
        self.assertEqual(manifest.entry("l1").input_hash, "h2")  # type: ignore[union-attr]


class StateTests(unittest.TestCase):
    def _entry(self, *, hash_: str = "h", days_ago: int = 0) -> DocEntry:
        stamp = (utcnow() - timedelta(days=days_ago)).isoformat()
        return DocEntry("l1", "a.md", hash_, stamp, "c")

    def test_without_entry_is_stale(self) -> None:
        self.assertIs(state_of(entry=None, current_hash="h"), DocState.STALE)

    def test_same_hash_is_fresh(self) -> None:
        self.assertIs(state_of(entry=self._entry(), current_hash="h"), DocState.FRESH)

    def test_changed_hash_is_stale(self) -> None:
        self.assertIs(state_of(entry=self._entry(hash_="old"), current_hash="new"), DocState.STALE)

    def test_old_entry_is_expired(self) -> None:
        entry = self._entry(days_ago=120)
        self.assertIs(state_of(entry=entry, current_hash="h", ttl_days=90), DocState.EXPIRED)


class InputHashTests(unittest.TestCase):
    def _hash(self, **overrides: object) -> str:
        params: dict[str, object] = dict(
            level="l1",
            sources={"a.java": "111"},
            fact_signature="sig",
            versions={"renderer": "1", "embedder": "onnx", "chunker": "ast-v2"},
            profile_digest="prof",
        )
        params.update(overrides)
        return input_hash_for(**params)  # type: ignore[arg-type]

    def test_is_stable(self) -> None:
        self.assertEqual(self._hash(), self._hash())

    def test_source_change_invalidates(self) -> None:
        self.assertNotEqual(self._hash(), self._hash(sources={"a.java": "222"}))

    def test_embedder_upgrade_invalidates(self) -> None:
        self.assertNotEqual(
            self._hash(),
            self._hash(versions={"renderer": "1", "embedder": "onnx-v2", "chunker": "ast-v2"}),
        )

    def test_profile_change_invalidates(self) -> None:
        self.assertNotEqual(self._hash(), self._hash(profile_digest="otro"))

    def test_fact_signature_uses_structure_only(self) -> None:
        class FakeFact:
            def __init__(self, kind: str, subject: str) -> None:
                self.kind = kind
                self.subject = subject

        first = fact_signature([FakeFact("module", "core"), FakeFact("type", "Api")])
        second = fact_signature([FakeFact("module", "core"), FakeFact("type", "Otro")])
        self.assertEqual(first, second)  # los tipos no son estructura de dependencias
        third = fact_signature([FakeFact("module", "extra"), FakeFact("type", "Api")])
        self.assertNotEqual(first, third)


class PipelineFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_repo(self.root)
        self.out = self.root / "docs" / "generated"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_generation_writes_manifest(self) -> None:
        result = generate(self.root, self.out, project="demo")
        self.assertIsNotNone(result.manifest_path)
        assert result.manifest_path is not None
        self.assertTrue(result.manifest_path.exists())
        self.assertEqual(set(result.states.values()), {DocState.STALE})

    def test_inspect_reports_fresh_after_generation(self) -> None:
        generate(self.root, self.out, project="demo")
        manifest, states, _hashes = inspect(self.root)
        self.assertIsNotNone(manifest)
        self.assertEqual(set(states.values()), {DocState.FRESH})

    def test_incremental_skips_fresh_pages(self) -> None:
        generate(self.root, self.out, project="demo")
        result = generate(self.root, self.out, project="demo", incremental=True)
        self.assertEqual(result.docs, ())
        self.assertEqual(set(result.states.values()), {DocState.FRESH})

    def test_incremental_regenerates_after_source_change(self) -> None:
        generate(self.root, self.out, project="demo")
        (self.root / "src" / "main" / "java" / "Api.java").write_text(
            JAVA + "\nclass Extra {}\n", encoding="utf-8"
        )
        _manifest, states, _hashes = inspect(self.root)
        self.assertEqual(set(states.values()), {DocState.STALE})
        result = generate(self.root, self.out, project="demo", incremental=True)
        self.assertEqual(len(result.docs), 2)
        self.assertIn("Extra", (self.out / "l1-manual-tecnico.md").read_text(encoding="utf-8"))

    def test_expired_page_is_regenerated(self) -> None:
        generate(self.root, self.out, project="demo", ttl_days=0)
        result = generate(self.root, self.out, project="demo", incremental=True, ttl_days=0)
        self.assertEqual(len(result.docs), 2)

    def test_profile_change_marks_stale(self) -> None:
        generate(self.root, self.out, project="demo")
        (self.root / "docu.profile.yaml").write_text("project: demo\n", encoding="utf-8")
        _manifest, states, _hashes = inspect(self.root)
        self.assertEqual(set(states.values()), {DocState.STALE})

    def test_deleted_document_is_not_fresh(self) -> None:
        """Un hash intacto con el archivo borrado no es frescura: es un registro que miente."""
        generate(self.root, self.out, project="demo")
        (self.out / "l1-manual-tecnico.md").unlink()
        _manifest, states, _hashes = inspect(self.root)
        self.assertIs(states["l1"], DocState.STALE)
        self.assertIs(states["l4"], DocState.FRESH)

    def test_manifest_is_not_written_when_gate_aborts(self) -> None:
        from unittest import mock

        from docu.generate.facts import Fact

        with mock.patch(
            "docu.generate.pipeline.java_facts",
            return_value=[Fact("route", "GET /x", "h", "")],
        ):
            result = generate(self.root, self.out, project="demo")
        assert result.manifest_path is not None
        self.assertFalse(result.manifest_path.exists())


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_repo(self.root)
        self.out = str(self.root / "docs" / "generated")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_status_without_manifest_asks_for_review(self) -> None:
        code, output = run_cli("status", "--root", str(self.root))
        self.assertEqual(code, int(ExitCode.NEEDS_REVIEW))
        self.assertIn("sin manifest", output)

    def test_status_after_generation_is_ok(self) -> None:
        run_cli("gen", "--root", str(self.root), "--out", self.out, "--project", "demo")
        code, output = run_cli("status", "--root", str(self.root))
        self.assertEqual(code, int(ExitCode.OK))
        self.assertIn("todo fresco", output)

    def test_gen_incremental_without_changes_returns_no_changes(self) -> None:
        run_cli("gen", "--root", str(self.root), "--out", self.out, "--project", "demo")
        code, output = run_cli("gen", "--root", str(self.root), "--out", self.out, "--incremental")
        self.assertEqual(code, int(ExitCode.NO_CHANGES))
        self.assertIn("sin cambios", output)

    def test_status_json_is_machine_readable(self) -> None:
        run_cli("gen", "--root", str(self.root), "--out", self.out, "--project", "demo")
        code, output = run_cli("status", "--root", str(self.root), "--json")
        self.assertEqual(code, int(ExitCode.OK))
        payload = json.loads(output)
        self.assertEqual(payload["states"], {"l1": "fresh", "l4": "fresh"})

    def test_ci_check_fails_on_stale(self) -> None:
        code, _output = run_cli("ci", "check", "--root", str(self.root))
        self.assertEqual(code, int(ExitCode.NEEDS_REVIEW))

    def test_ci_regen_writes_pr_body(self) -> None:
        code, output = run_cli("ci", "regen", "--root", str(self.root), "--out", self.out)
        body = self.root / ".docu" / "pr-body.md"
        self.assertEqual(code, int(ExitCode.OK))
        self.assertTrue(body.exists())
        content = body.read_text(encoding="utf-8")
        self.assertIn("Documentación regenerada", content)
        self.assertIn("| l1 |", content)
        self.assertIn("Archivos actualizados", content)
        self.assertIn("PR body", output)


class HashHygieneTests(unittest.TestCase):
    def test_source_hash_is_truncated_and_prefixed(self) -> None:
        digest = sha256_of("contenido")
        self.assertTrue(digest.startswith("sha256:"))
        self.assertEqual(len(digest), len("sha256:") + 64)


if __name__ == "__main__":
    unittest.main()
