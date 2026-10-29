"""Diagramas Mermaid derivados de evidencia: paquetes, clases y flujo de API."""

from __future__ import annotations

import unittest

from docu.generate.diagrams import (
    Diagram,
    api_flow_diagram,
    architecture_diagram,
    build_all,
    class_diagram,
    package_dependencies,
    resolve_import,
    write_diagrams,
)
from docu.generate.facts import Fact
from docu.index.packages import DetectedPackage


def package(name: str, files: tuple[str, ...]) -> DetectedPackage:
    return DetectedPackage(
        name=name, language="python", files=files, declaration=f"{files[0]}#L1-L1"
    )


class ResolveImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.packages = (
            package("demo", ("src/demo/__init__.py", "src/demo/app.py")),
            package("demo.core", ("src/demo/core/__init__.py", "src/demo/core/models.py")),
        )

    def test_absolute_import_resolves_to_longest_package(self) -> None:
        self.assertEqual(
            resolve_import("demo.core.models", "src/demo/app.py", self.packages), "demo.core"
        )

    def test_external_import_is_ignored(self) -> None:
        self.assertIsNone(resolve_import("requests", "src/demo/app.py", self.packages))

    def test_relative_import_resolves_by_path(self) -> None:
        self.assertEqual(
            resolve_import("./core/models", "src/demo/app.py", self.packages), "demo.core"
        )

    def test_root_package_import_does_not_capture_subpackage(self) -> None:
        self.assertEqual(resolve_import("demo.app", "x.py", self.packages), "demo")


class ArchitectureTests(unittest.TestCase):
    def test_diagram_lists_packages_and_edges(self) -> None:
        packages = (package("a", ("a/x.py",)), package("b", ("b/y.py",)))
        diagram = architecture_diagram(packages, {("a", "b"): {"a/x.py"}})
        assert diagram is not None
        self.assertIn("flowchart LR", diagram.mermaid)
        self.assertIn('a["a<br/>1 archivos"]', diagram.mermaid)
        self.assertIn("a --> b", diagram.mermaid)

    def test_without_edges_it_still_renders(self) -> None:
        diagram = architecture_diagram((package("a", ("a/x.py",)),), {})
        assert diagram is not None
        self.assertIn("sin dependencias", diagram.mermaid)

    def test_no_packages_means_no_diagram(self) -> None:
        self.assertIsNone(architecture_diagram((), {}))

    def test_dependencies_ignore_external_and_self(self) -> None:
        files = {"src/demo/app.py": None, "src/demo/core/models.py": None}  # type: ignore[dict-item]
        packages = (
            package("demo", ("src/demo/__init__.py", "src/demo/app.py")),
            package("demo.core", ("src/demo/core/__init__.py", "src/demo/core/models.py")),
        )

        class FakeAdapter:
            language = "python"

            def imports(self, path: str, source: str) -> tuple[str, ...]:
                return ("demo.core.models", "requests") if path.endswith("app.py") else ()

        original = package_dependencies.__globals__.get("adapter_for")
        try:
            package_dependencies.__globals__["adapter_for"] = lambda path: FakeAdapter()
            edges = package_dependencies(files, packages, lambda path: "")
        finally:
            package_dependencies.__globals__["adapter_for"] = original
        self.assertEqual(set(edges), {("demo", "demo.core")})


class ClassDiagramTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facts = [
            Fact("type", "JwtService", "class", "src/demo/jwt.py#L1-L30",
                 {"signature": "public class JwtService extends BaseService implements Tokens"}),
            Fact("type", "BaseService", "class", "src/demo/base.py#L1-L9", {"signature": "class BaseService"}),
            Fact("method", "JwtService.verify", "public boolean verify(String token)", "src/demo/jwt.py#L10-L20"),
        ]

    def test_renders_classes_methods_and_inheritance(self) -> None:
        diagram = class_diagram(
            package("demo", ("src/demo/jwt.py", "src/demo/base.py")), self.facts
        )
        assert diagram is not None
        self.assertIn("classDiagram", diagram.mermaid)
        self.assertIn("class JwtService <<class>> {", diagram.mermaid)
        self.assertIn("verify()", diagram.mermaid)
        self.assertIn("BaseService <|-- JwtService", diagram.mermaid)

    def test_stereotype_is_outside_the_body(self) -> None:
        diagram = class_diagram(package("demo", ("src/demo/jwt.py",)), self.facts)
        assert diagram is not None
        body = diagram.mermaid.split("class JwtService <<class>> {")[1].split("}")[0]
        self.assertNotIn("<<", body)

    def test_package_without_types_has_no_diagram(self) -> None:
        self.assertIsNone(class_diagram(package("vacio", ("vacio/x.py",)), self.facts))


class ApiFlowTests(unittest.TestCase):
    def test_routes_become_nodes_under_their_handler(self) -> None:
        facts = [
            Fact("route", "GET /api/x", "Ctl.getX", "a.py#L1-L2", {"verb": "GET", "path": "/api/x", "handler": "Ctl.getX"}),
            Fact("route", "POST /api/y", "Ctl.postY", "a.py#L3-L4", {"verb": "POST", "path": "/api/y", "handler": "Ctl.postY"}),
        ]
        diagram = api_flow_diagram(facts)
        assert diagram is not None
        self.assertIn('cliente -->', diagram.mermaid)
        self.assertIn("GET /api/x", diagram.mermaid)
        self.assertIn("POST /api/y", diagram.mermaid)
        # dos rutas, un solo nodo de handler
        self.assertEqual(diagram.mermaid.count("Ctl\""), 1)

    def test_no_routes_means_no_diagram(self) -> None:
        self.assertIsNone(api_flow_diagram([]))


class BuildAllTests(unittest.TestCase):
    def test_bundles_available_diagrams(self) -> None:
        packages = (package("demo", ("src/demo/__init__.py", "src/demo/app.py")),)
        facts = [Fact("type", "App", "class", "src/demo/app.py#L1-L5", {"signature": "class App"})]
        diagrams = build_all({"src/demo/app.py": None}, packages, facts, lambda path: "")  # type: ignore[dict-item]
        names = [diagram.name for diagram in diagrams]
        self.assertIn("arquitectura", names)
        self.assertIn("clases-demo", names)

    def test_limit_on_class_diagrams(self) -> None:
        packages = tuple(
            package(f"p{index}", (f"p{index}/x.py",)) for index in range(6)
        )
        facts = [
            Fact("type", f"C{index}", "class", f"p{index}/x.py#L1-L2", {"signature": "class C"})
            for index in range(6)
        ]
        diagrams = build_all({}, packages, facts, lambda path: "")
        self.assertLessEqual(sum(1 for d in diagrams if d.kind == "classes"), 3)


class WriteTests(unittest.TestCase):
    def test_writes_and_removes_stale(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "obsoleto.mmd").write_text("viejo", encoding="utf-8")
            written = write_diagrams(
                [Diagram("nuevo", "architecture", "flowchart LR\n    a --> b")], directory
            )
            self.assertEqual([path.name for path in written], ["nuevo.mmd"])
            self.assertFalse((directory / "obsoleto.mmd").exists())
            self.assertIn("a --> b", (directory / "nuevo.mmd").read_text(encoding="utf-8"))

    def test_no_diagrams_writes_nothing(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(write_diagrams((), Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
