"""`docu clean`: volver a cero sin borrar lo que no generó docu."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docu.delivery.cleanup import apply, plan


def build_repo(root: Path) -> Path:
    docs = root / "docs" / "generated"
    (docs / "diagrams").mkdir(parents=True)
    (docs / "site" / "assets").mkdir(parents=True)
    (docs / "l1-manual-tecnico.md").write_text("# manual\n", encoding="utf-8")
    (docs / "l4-readme.md").write_text("# readme\n", encoding="utf-8")
    (docs / "diagrams" / "arquitectura.mmd").write_text("flowchart LR\n", encoding="utf-8")
    (docs / "site" / "index.html").write_text("<html></html>", encoding="utf-8")
    (docs / "site" / "assets" / "site.css").write_text("body{}", encoding="utf-8")
    state = root / ".docu"
    state.mkdir()
    (state / "manifest.json").write_text("{}", encoding="utf-8")
    (state / "prose.json").write_text("{}", encoding="utf-8")
    (state / "ledger.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "docu.profile.yaml").write_text("schema_version: '1.0'\n", encoding="utf-8")
    (root / "docs" / "hecho-a-mano.md").write_text("# escrito por una persona\n", encoding="utf-8")
    return docs


class PlanTests(unittest.TestCase):
    def test_plan_lists_documents_artifacts_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = build_repo(root)
            result = plan(root, docs)
            self.assertEqual(len(result.documents), 2)
            self.assertGreaterEqual(len(result.artifacts), 3)
            self.assertEqual(len(result.state), 2)  # manifest + prose
            self.assertEqual(result.ledger, [])  # el ledger no se borra por defecto

    def test_ledger_only_when_asked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = build_repo(root)
            self.assertEqual(len(plan(root, docs, ledger=True).ledger), 1)

    def test_hand_written_docs_are_never_touched(self) -> None:
        """El directorio `docs/` puede tener documentación escrita a mano: no se toca."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = build_repo(root)
            result = plan(root, docs)
            paths = {str(path) for path in [*result.documents, *result.artifacts, *result.state]}
            self.assertFalse(any("hecho-a-mano" in path for path in paths))

    def test_profile_is_never_touched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = build_repo(root)
            result = plan(root, docs, ledger=True)
            paths = {str(path) for path in [*result.documents, *result.artifacts, *result.state, *result.ledger]}
            self.assertFalse(any("docu.profile.yaml" in path for path in paths))

    def test_docs_only_and_state_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = build_repo(root)
            only_docs = plan(root, docs, state=False)
            self.assertTrue(only_docs.documents)
            self.assertEqual(only_docs.state, [])
            only_state = plan(root, docs, documents=False)
            self.assertEqual(only_state.documents, [])
            self.assertTrue(only_state.state)

    def test_nothing_to_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "generated").mkdir(parents=True)
            result = plan(root, root / "docs" / "generated")
            self.assertTrue(result.empty)
            self.assertEqual(result.total, 0)

    def test_outside_root_is_warned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "generated").mkdir(parents=True)
            (root / "docs" / "generated" / "x.md").write_text("# x\n", encoding="utf-8")
            external = root.parent / "otro-proyecto-docs"
            result = plan(root, external)
            self.assertTrue(result.warnings)
            self.assertTrue(any("fuera del proyecto" in warning for warning in result.warnings))


class ApplyTests(unittest.TestCase):
    def test_apply_removes_only_the_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = build_repo(root)
            removed, errors = apply(plan(root, docs))
            self.assertEqual(errors, [])
            self.assertEqual(removed, 7)
            self.assertFalse((docs / "l1-manual-tecnico.md").exists())
            self.assertFalse((docs / "diagrams" / "arquitectura.mmd").exists())
            self.assertFalse((root / ".docu" / "manifest.json").exists())
            # lo que no generó docu sigue ahí
            self.assertTrue((root / "docu.profile.yaml").is_file())
            self.assertTrue((root / "docs" / "hecho-a-mano.md").is_file())
            self.assertTrue((root / ".docu" / "ledger.jsonl").is_file())

    def test_apply_with_ledger_removes_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = build_repo(root)
            apply(plan(root, docs, ledger=True))
            self.assertFalse((root / ".docu" / "ledger.jsonl").exists())

    def test_double_apply_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = build_repo(root)
            apply(plan(root, docs))
            removed, errors = apply(plan(root, docs))
            self.assertEqual((removed, errors), (0, []))


class CliTests(unittest.TestCase):
    def test_clean_command_simulates_then_deletes(self) -> None:
        from docu.delivery.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = build_repo(root)
            self.assertEqual(main(["clean", "--root", str(root), "--out", str(docs)]), 0)
            self.assertTrue((docs / "l1-manual-tecnico.md").exists(), "sin --force no borra")
            self.assertEqual(main(["clean", "--root", str(root), "--out", str(docs), "--force"]), 0)
            self.assertFalse((docs / "l1-manual-tecnico.md").exists())
            self.assertFalse((root / ".docu" / "manifest.json").exists())
            self.assertEqual(main(["clean", "--root", str(root), "--out", str(docs), "--force"]), 10)

    def test_docs_only_keeps_the_state(self) -> None:
        from docu.delivery.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = build_repo(root)
            main(["clean", "--root", str(root), "--out", str(docs), "--docs-only", "--force"])
            self.assertFalse((docs / "l1-manual-tecnico.md").exists())
            self.assertTrue((root / ".docu" / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
