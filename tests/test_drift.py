"""Deriva arquitectonica: lo declarado frente a lo implementado, en ambos sentidos."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from docu.conformance.drift import analyze, bootstrap, compare, describe_code
from docu.conformance.model import (
    ArchitectureModel,
    DeclaredComponent,
    Route,
    load_architecture,
    to_yaml,
)
from docu.core.yamlmini import YamlError, parse
from docu.delivery.cli import main
from docu.delivery.exit_codes import ExitCode

JAVA = '''package com.example;

import com.example.Helper;

@RestController
@RequestMapping("/api")
public class ApiController {
    private final Helper helper;

    @GetMapping("/ping")
    public String ping() { return helper.value(); }

    @PostMapping("/extra")
    public String extra() { return "x"; }
}
'''

HELPER = '''package com.example;

public class Helper {
    public String value() { return "v"; }
}
'''

ARCHITECTURE = '''architecture:
  components:
    - name: ApiController
      kind: service
      provides: ["GET /api/ping", "GET /api/ghost"]
      depends_on: [Helper]
    - name: Helper
      kind: service
      provides: []
      depends_on: []
    - name: Fantasma
      kind: service
      provides: []
      depends_on: []
'''


def run_cli(*argv: str) -> tuple[int, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        code = main(list(argv))
    return code, buffer.getvalue()


def build_repo(root: Path) -> None:
    (root / "src" / "main" / "java").mkdir(parents=True)
    (root / "src" / "main" / "java" / "ApiController.java").write_text(JAVA, encoding="utf-8")
    (root / "src" / "main" / "java" / "Helper.java").write_text(HELPER, encoding="utf-8")


class YamlTests(unittest.TestCase):
    def test_nested_maps_and_sequences(self) -> None:
        document = parse(
            "root:\n"
            "  items:\n"
            "    - name: a\n"
            "      value: 1\n"
            "    - name: b\n"
            "      value: 2\n"
        )
        items = document["root"]["items"]  # type: ignore[index]
        self.assertEqual([item["name"] for item in items], ["a", "b"])
        self.assertEqual(items[0]["value"], 1)

    def test_flow_lists_and_maps(self) -> None:
        document = parse('a: [1, "dos", true]\nb: {x: 1, y: z}\n')
        self.assertEqual(document["a"], [1, "dos", True])
        self.assertEqual(document["b"], {"x": 1, "y": "z"})

    def test_comments_and_quotes_are_respected(self) -> None:
        document = parse('key: "valor # no es comentario"  # esto si\n')
        self.assertEqual(document["key"], "valor # no es comentario")

    def test_scalars_are_typed(self) -> None:
        document = parse("i: 3\nf: 1.5\nb: false\nn: null\ns: texto\n")
        self.assertEqual(document["i"], 3)
        self.assertEqual(document["f"], 1.5)
        self.assertIs(document["b"], False)
        self.assertIsNone(document["n"])
        self.assertEqual(document["s"], "texto")

    def test_bad_indentation_raises(self) -> None:
        with self.assertRaises(YamlError):
            parse("a:\n    b: 1\n  c: 2\n")

    def test_empty_document(self) -> None:
        self.assertEqual(parse("# solo comentarios\n\n"), {})


class ModelTests(unittest.TestCase):
    def test_openapi_routes_are_declared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "openapi.yaml").write_text(
                "openapi: 3.0.0\npaths:\n  /api/ping:\n    get:\n      summary: ping\n"
                "  /api/orders:\n    post:\n      summary: crear\n",
                encoding="utf-8",
            )
            model = load_architecture(root)
        self.assertEqual(model.declared_routes, {"GET /api/ping", "POST /api/orders"})

    def test_no_artifacts_yields_empty_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model = load_architecture(Path(tmp))
        self.assertTrue(model.is_empty)

    def test_roundtrip_via_yaml(self) -> None:
        model = ArchitectureModel(
            components=(
                DeclaredComponent("A", "service", (Route("GET", "/x"),), ("B",), "architecture.yaml"),
                DeclaredComponent("B"),
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "architecture.yaml"
            path.write_text(to_yaml(model, "demo"), encoding="utf-8")
            restored = load_architecture(Path(tmp))
        self.assertEqual(restored.component_names, {"A", "B"})
        self.assertEqual(restored.declared_routes, {"GET /x"})
        self.assertEqual(restored.declared_dependencies(), {("A", "B")})


class CompareTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_repo(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_code_is_described_faithfully(self) -> None:
        code = describe_code(self.root)
        self.assertEqual({route.key for route in code.routes}, {"GET /api/ping", "POST /api/extra"})
        self.assertIn("ApiController", code.components)
        self.assertTrue(any("Helper" in callee for _caller, callee in code.dependencies))

    def test_detects_all_four_kinds(self) -> None:
        model = load_architecture(self.root, self._write(ARCHITECTURE))
        report = compare(model, describe_code(self.root))
        kinds = {item.kind for item in report.discrepancies}
        self.assertIn("undeclared_route", kinds)  # POST /api/extra existe y no se declara
        self.assertIn("missing_implementation", kinds)  # GET /api/ghost declarada y ausente
        self.assertIn("missing_component", kinds)  # Fantasma
        self.assertFalse(report.is_clean)

    def test_clean_model_has_no_drift(self) -> None:
        model = bootstrap(self.root)
        report = compare(model, describe_code(self.root))
        self.assertTrue(report.is_clean, msg=str(report.to_dict()))

    def test_bootstrap_includes_routes_and_dependencies(self) -> None:
        model = bootstrap(self.root)
        controller = next(item for item in model.components if item.name == "ApiController")
        self.assertEqual({route.key for route in controller.provides}, {"GET /api/ping", "POST /api/extra"})
        self.assertIn("Helper", controller.depends_on)

    def test_missing_dependency_is_reported(self) -> None:
        model = ArchitectureModel(
            components=(DeclaredComponent("ApiController", depends_on=("Inexistente",)),)
        )
        report = compare(model, describe_code(self.root))
        self.assertIn("missing_dependency", {item.kind for item in report.discrepancies})

    def test_report_serializes_and_renders(self) -> None:
        model = load_architecture(self.root, self._write(ARCHITECTURE))
        report = compare(model, describe_code(self.root))
        payload = json.loads(json.dumps(report.to_dict()))
        self.assertGreater(payload["errors"] + payload["warnings"], 0)
        self.assertIn("Deriva arquitectónica", report.to_markdown())

    def _write(self, content: str) -> Path:
        path = self.root / "architecture.yaml"
        path.write_text(content, encoding="utf-8")
        return path


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_repo(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_without_model_returns_config_error(self) -> None:
        code, output = run_cli("drift", "--root", str(self.root))
        self.assertEqual(code, int(ExitCode.CONFIG_ERROR))
        self.assertIn("bootstrap", output)

    def test_bootstrap_then_check_is_clean(self) -> None:
        code, _output = run_cli("drift", "--root", str(self.root), "--bootstrap")
        self.assertEqual(code, int(ExitCode.OK))
        self.assertTrue((self.root / "architecture.yaml").exists())
        code, output = run_cli("drift", "--root", str(self.root))
        self.assertEqual(code, int(ExitCode.OK))
        self.assertIn("Sin discrepancias", output)

    def test_declared_ghost_route_fails(self) -> None:
        (self.root / "architecture.yaml").write_text(ARCHITECTURE, encoding="utf-8")
        code, output = run_cli("drift", "--root", str(self.root))
        self.assertEqual(code, int(ExitCode.NEEDS_REVIEW))
        self.assertIn("missing_implementation", output)

    def test_json_output_is_machine_readable(self) -> None:
        (self.root / "architecture.yaml").write_text(ARCHITECTURE, encoding="utf-8")
        code, output = run_cli("drift", "--root", str(self.root), "--json")
        self.assertEqual(code, int(ExitCode.NEEDS_REVIEW))
        payload = json.loads(output)
        self.assertIn("discrepancies", payload)
        self.assertGreater(payload["errors"], 0)


if __name__ == "__main__":
    unittest.main()
