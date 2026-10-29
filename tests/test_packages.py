"""Paquetes como unidad arquitectónica: detección, evidencia y efecto en la compuerta."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docu.generate.facts import Fact
from docu.generate.markdown import NO_EVIDENCE, render_l1
from docu.generate.pipeline import applicability, completeness, generate
from docu.index.packages import detect_packages, top_level

JAVA_A = """package com.acme.core;

public class A {}
"""

JAVA_B = """package com.acme.core;

public class B {}
"""

JAVA_C = """package com.acme.api;

public class C {}
"""


def build_python_repo(root: Path) -> None:
    (root / "src" / "demo" / "core").mkdir(parents=True)
    (root / "src" / "demo" / "__init__.py").write_text('"""Paquete demo."""\n', encoding="utf-8")
    (root / "src" / "demo" / "core" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "demo" / "core" / "models.py").write_text("class Model:\n    pass\n", encoding="utf-8")
    (root / "src" / "demo" / "service.py").write_text("def run() -> None:\n    pass\n", encoding="utf-8")
    # Directorio SIN __init__.py: no es paquete, no genera hecho.
    (root / "src" / "demo" / "utils").mkdir()
    (root / "src" / "demo" / "utils" / "helper.py").write_text("def helper() -> None:\n    pass\n", encoding="utf-8")


class PythonPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_python_repo(self.root)
        self.files = {
            rel: self.root / rel
            for rel in (
                "src/demo/__init__.py",
                "src/demo/core/__init__.py",
                "src/demo/core/models.py",
                "src/demo/service.py",
                "src/demo/utils/helper.py",
            )
        }
        self.packages = {package.name: package for package in detect_packages(self.files)}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_uses_dotted_name_without_src_prefix(self) -> None:
        self.assertIn("demo", self.packages)
        self.assertIn("demo.core", self.packages)

    def test_directory_without_init_is_not_a_package(self) -> None:
        self.assertNotIn("demo.utils", self.packages)

    def test_counts_only_its_own_files(self) -> None:
        self.assertEqual(self.packages["demo.core"].file_count, 2)  # __init__ + models
        self.assertEqual(self.packages["demo"].file_count, 5)  # todo lo anidado

    def test_citation_points_to_the_declaring_file(self) -> None:
        self.assertEqual(self.packages["demo.core"].citation, "src/demo/core/__init__.py#L1-L1")

    def test_top_level_roots(self) -> None:
        self.assertEqual(top_level(tuple(self.packages.values())), ("demo",))


class JavaPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "a").mkdir()
        (self.root / "a" / "A.java").write_text(JAVA_A, encoding="utf-8")
        (self.root / "a" / "B.java").write_text(JAVA_B, encoding="utf-8")
        (self.root / "c").mkdir()
        (self.root / "c" / "C.java").write_text(JAVA_C, encoding="utf-8")
        self.files = {
            "a/A.java": self.root / "a" / "A.java",
            "a/B.java": self.root / "a" / "B.java",
            "c/C.java": self.root / "c" / "C.java",
        }
        self.packages = {package.name: package for package in detect_packages(self.files)}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_groups_files_by_declared_package(self) -> None:
        self.assertEqual(self.packages["com.acme.core"].file_count, 2)
        self.assertEqual(self.packages["com.acme.api"].file_count, 1)

    def test_citation_is_the_package_statement_line(self) -> None:
        self.assertEqual(self.packages["com.acme.core"].citation, "a/A.java#L1-L1")

    def test_file_without_package_statement_is_ignored(self) -> None:
        (self.root / "d").mkdir()
        (self.root / "d" / "D.java").write_text("public class D {}\n", encoding="utf-8")
        packages = detect_packages({"d/D.java": self.root / "d" / "D.java"})
        self.assertEqual(packages, ())


class TypeScriptPackageTests(unittest.TestCase):
    def test_index_barrel_is_a_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "web" / "ui").mkdir(parents=True)
            (root / "web" / "ui" / "index.ts").write_text("export const x = 1;\n", encoding="utf-8")
            (root / "web" / "ui" / "button.ts").write_text("export const b = 1;\n", encoding="utf-8")
            packages = detect_packages(
                {
                    "web/ui/index.ts": root / "web" / "ui" / "index.ts",
                    "web/ui/button.ts": root / "web" / "ui" / "button.ts",
                }
            )
        self.assertEqual(len(packages), 1)
        self.assertEqual(packages[0].name, "web.ui")
        self.assertEqual(packages[0].file_count, 2)


class CompletenessWithPackagesTests(unittest.TestCase):
    def _facts(self, kinds: set[str]) -> list[Fact]:
        return [Fact(kind=kind, subject=f"{kind}-1", detail="", citation="x#L1-L1") for kind in kinds]

    def test_packages_count_as_module_evidence(self) -> None:
        applicable = {"module": True, "type": True, "dependency": False, "route": False, "config_key": False}
        facts = self._facts({"package", "type"})
        self.assertEqual(completeness(facts, applicable), 10.0)

    def test_maven_module_still_counts(self) -> None:
        applicable = {"module": True, "type": False, "dependency": False, "route": False, "config_key": False}
        self.assertEqual(completeness(self._facts({"module"}), applicable), 10.0)

    def test_missing_structure_lowers_score(self) -> None:
        applicable = {"module": True, "type": True, "dependency": False, "route": False, "config_key": False}
        self.assertEqual(completeness(self._facts({"type"}), applicable), 5.0)


class ApplicabilityTests(unittest.TestCase):
    def test_python_project_without_packages_does_not_require_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("def f() -> None:\n    pass\n", encoding="utf-8")
            facts = [Fact("type", "X", "class", "app.py#L1-L1")]
            self.assertFalse(applicability(facts, root)["module"])

    def test_python_project_with_packages_requires_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            facts = [Fact("package", "demo", "1 archivos", "src/demo/__init__.py#L1-L1")]
            self.assertTrue(applicability(facts, root)["module"])


class RenderTests(unittest.TestCase):
    def test_package_table_is_rendered_with_citation(self) -> None:
        facts = [Fact("package", "docu.core", "6 archivos · python", "src/docu/core/__init__.py#L1-L6"),
                 Fact("type", "Chunk", "class", "src/docu/core/contracts.py#L1-L10")]
        document = render_l1("docu", facts, {"src/x.py": "abc"}, {"version": "0.1.0"})
        self.assertIn("Paquete", document)
        self.assertIn("`docu.core`", document)
        self.assertIn("src/docu/core/__init__.py#L1-L6", document)

    def test_section_abstains_only_when_there_is_neither_module_nor_package(self) -> None:
        facts = [Fact("type", "X", "class", "a.py#L1-L1")]
        document = render_l1("demo", facts, {"a.py": "abc"}, {"version": "0.1.0"})
        self.assertIn(NO_EVIDENCE, document)


class PipelinePackageTests(unittest.TestCase):
    def test_python_repo_documents_packages_and_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pyrepo"
            out = root / "docs"
            build_python_repo(root)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "demo"\ndependencies = ["requests>=2"]\n', encoding="utf-8"
            )
            (root / "settings.yml").write_text("a:\n  b: 1\n", encoding="utf-8")
            result = generate(root, out, project="demo")
            subjects = {fact.subject for fact in result.facts if fact.kind == "package"}
            self.assertIn("demo.core", subjects)
            self.assertTrue(result.applicability["module"])
            self.assertIn("paquetes", (out / "l1-manual-tecnico.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
