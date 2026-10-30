"""Generador: hechos con cita, huecos declarados e idempotencia byte a byte."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from docu.core.contracts import GateOutcome, SymbolKind
from docu.generate.facts import Fact, java_facts, pom_facts, unsupported, yaml_facts
from docu.generate.markdown import NO_EVIDENCE, render_l1, render_l4
from docu.generate.pipeline import generate

JAVA = '''package com.example;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api")
public class WidgetController {

    @GetMapping("/widgets")
    public String list() {
        return "ok";
    }
}
'''

YAML = """server:
  port: 8089
spring:
  application:
    name: widget-service
bss:
  cache:
    enabled: true
"""

POM = """<project>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.3.4</version>
  </parent>
  <properties>
    <java.version>21</java.version>
  </properties>
  <modules>
    <module>core</module>
    <module>app</module>
  </modules>
  <dependencies>
    <dependency>
      <groupId>io.jsonwebtoken</groupId>
      <artifactId>jjwt-api</artifactId>
      <version>0.12.6</version>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <artifactId>spring-boot-maven-plugin</artifactId>
      </plugin>
    </plugins>
  </build>
</project>
"""


def build_repo(root: Path) -> None:
    (root / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
    (root / "src" / "main" / "java" / "com" / "example" / "WidgetController.java").write_text(
        JAVA, encoding="utf-8"
    )
    (root / "src" / "main" / "resources").mkdir(parents=True)
    (root / "src" / "main" / "resources" / "application.yml").write_text(YAML, encoding="utf-8")
    (root / "pom.xml").write_text(POM, encoding="utf-8")


class YamlFactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facts = yaml_facts("application.yml", YAML)

    def test_nested_keys_are_flattened(self) -> None:
        keys = {fact.subject for fact in self.facts}
        self.assertIn("server.port", keys)
        self.assertIn("spring.application.name", keys)
        self.assertIn("bss.cache.enabled", keys)

    def test_values_and_lines_are_exact(self) -> None:
        port = next(fact for fact in self.facts if fact.subject == "server.port")
        self.assertEqual(port.detail, "8089")
        self.assertEqual(port.citation, "application.yml#L2-L2")

    def test_section_headers_are_not_facts(self) -> None:
        self.assertNotIn("server", {fact.subject for fact in self.facts})

    def test_comments_are_ignored(self) -> None:
        facts = yaml_facts("a.yml", "# comentario\n# clave: valor\nreal: 1\n")
        self.assertEqual([fact.subject for fact in facts], ["real"])


class PomFactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facts = pom_facts("pom.xml", POM)

    def test_modules_are_extracted(self) -> None:
        modules = {f.subject for f in self.facts if f.kind == "module"}
        self.assertEqual(modules, {"core", "app"})

    def test_property_and_parent_are_extracted(self) -> None:
        kinds = {f.kind for f in self.facts}
        self.assertIn("property", kinds)
        self.assertIn("parent", kinds)
        parent = next(f for f in self.facts if f.kind == "parent")
        self.assertEqual(parent.detail, "3.3.4")

    def test_dependency_has_group_version_scope(self) -> None:
        dependency = next(f for f in self.facts if f.kind == "dependency")
        self.assertEqual(dependency.subject, "io.jsonwebtoken:jjwt-api")
        self.assertEqual(dependency.detail, "0.12.6")
        self.assertEqual(dependency.attributes["scope"], "compile")

    def test_plugin_is_extracted_for_onboarding(self) -> None:
        plugins = {f.subject for f in self.facts if f.kind == "plugin"}
        self.assertIn("spring-boot-maven-plugin", plugins)

    def test_every_fact_has_a_citation(self) -> None:
        self.assertEqual(unsupported(self.facts), [])


class JavaFactTests(unittest.TestCase):
    def setUp(self) -> None:
        from docu.adapters.langs.java import JavaLangAdapter

        symbols = JavaLangAdapter().symbols("WidgetController.java", JAVA)
        self.facts = java_facts(symbols)

    def test_type_method_and_route_are_documented(self) -> None:
        kinds = {fact.kind for fact in self.facts}
        self.assertEqual(kinds, {"type", "method", "route"})

    def test_route_carries_verb_path_and_handler(self) -> None:
        route = next(fact for fact in self.facts if fact.kind == "route")
        self.assertEqual(route.attributes["verb"], "GET")
        self.assertEqual(route.attributes["path"], "/api/widgets")
        self.assertEqual(route.attributes["handler"], "WidgetController.list")

    def test_method_fact_includes_signature(self) -> None:
        method = next(fact for fact in self.facts if fact.kind == "method")
        self.assertIn("list()", method.detail)
        self.assertEqual(method.subject, "WidgetController.list")

    def test_citation_points_to_the_declaration_lines(self) -> None:
        type_fact = next(fact for fact in self.facts if fact.kind == "type")
        self.assertRegex(type_fact.citation, r"WidgetController\.java#L\d+-L\d+")


class UnsupportedTests(unittest.TestCase):
    def test_fact_without_citation_is_rejected(self) -> None:
        facts = [Fact(kind="route", subject="GET /x", detail="h", citation="")]
        self.assertEqual(len(unsupported(facts)), 1)


class RendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facts = [Fact("module", "core", "modulo Maven", "pom.xml#L1-L1", {"module": "core"})]
        self.sources = {"pom.xml": "abc123"}
        self.meta = {"version": "0.1.0", "digest": "sha256:x", "sources": "1", "unsupported": "0"}

    def test_missing_sections_are_declared_not_invented(self) -> None:
        document = render_l1("demo", self.facts, self.sources, self.meta)
        self.assertIn(NO_EVIDENCE, document)
        self.assertIn("Sin evidencia", document)

    def test_every_table_row_carries_a_citation(self) -> None:
        document = render_l1("demo", self.facts, self.sources, self.meta)
        # La seccion de trazabilidad lista los archivos fuente y su huella: ahi la cita no aplica.
        body = document.split("## 14. Trazabilidad")[0]
        for line in body.splitlines():
            if line.startswith("| `"):
                self.assertIn("#L", line, msg=f"fila sin cita: {line}")

    def test_header_is_deterministic(self) -> None:
        first = render_l1("demo", self.facts, self.sources, self.meta)
        second = render_l1("demo", self.facts, self.sources, self.meta)
        self.assertEqual(first, second)

    def test_onboarding_readme_has_prerequisites(self) -> None:
        facts = self.facts + [Fact("property", "java.version", "21", "pom.xml#L2-L2")]
        document = render_l4("demo", facts, self.sources, self.meta)
        self.assertIn("## Prerrequisitos", document)
        self.assertIn("java.version", document)


class OnboardingTests(unittest.TestCase):
    """Nivel 3: la promesa es «sin jerga», y eso se puede medir."""

    def setUp(self) -> None:
        self.facts = [
            Fact("route", "GET /api/x", "C.m", "A.java#L3-L4", {"verb": "GET", "path": "/api/x"}),
            Fact("config_key", "a.b", "1", "application.yml#L2-L2", {"key": "a.b", "value": "1"}),
        ]
        self.meta = {"version": "0.1.0", "digest": "sha256:x", "sources": "1", "unsupported": "0"}

    def test_l3_translates_verbs_to_plain_actions(self) -> None:
        from docu.generate.markdown import render_l3

        document = render_l3("demo", self.facts, {"a.java": "x"}, self.meta)
        self.assertIn("Consultar información", document)
        self.assertIn("## Qué puedes hacer", document)

    def test_l3_declares_missing_faq(self) -> None:
        from docu.generate.markdown import NO_EVIDENCE_MARKER, render_l3

        document = render_l3("demo", self.facts, {"a.java": "x"}, self.meta)
        self.assertIn(NO_EVIDENCE_MARKER, document)

    def test_l3_prose_has_no_jargon(self) -> None:
        import re

        from docu.generate.markdown import JARGON, render_l3

        document = render_l3("demo", self.facts, {"a.java": "x"}, self.meta)
        prose = re.sub(r"`[^`]*`", "", document)  # las rutas y claves son código, no prosa
        lowered = prose.lower()
        for term in JARGON:
            self.assertNotIn(term, lowered, msg=f"jerga prohibida en Nivel 3: {term}")


class DryRunTests(unittest.TestCase):
    """`--dry-run` existe para probar sobre un repositorio ajeno sin dejar rastro."""

    def test_dry_run_writes_no_files(self) -> None:
        from docu.generate.pipeline import generate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "demo.py").write_text("class Demo:\n    valor: int = 1\n", encoding="utf-8")
            out = root / "salida"
            result = generate(root, out, levels=("l1", "l4"), dry_run=True)
            self.assertFalse(out.exists(), "no debe crear el directorio de salida")
            self.assertFalse((root / ".docu").exists(), "no debe crear .docu (manifest ni ledger)")
            self.assertTrue(result.dry_run)
            self.assertFalse(result.wrote_files)
            self.assertTrue(result.docs, "sí debe renderizar para validar la compuerta")


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_repo(self.root)
        self.out = self.root / "docs" / "generated"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_generation_writes_both_levels(self) -> None:
        result = generate(self.root, self.out, project="demo")
        self.assertEqual(len(result.docs), 2)
        self.assertTrue((self.out / "l1-manual-tecnico.md").exists())
        self.assertTrue((self.out / "l4-readme.md").exists())
        self.assertIs(result.gate.outcome, GateOutcome.PUBLISH)

    def test_metrics_reflect_real_evidence(self) -> None:
        result = generate(self.root, self.out, project="demo")
        self.assertEqual(result.metrics.unsupported_claims, 0)
        self.assertGreater(result.metrics.completeness, 0.0)
        self.assertGreater(len(result.facts), 10)

    def test_output_is_byte_identical_across_runs(self) -> None:
        first = generate(self.root, self.out, project="demo")
        content_first = (self.out / "l1-manual-tecnico.md").read_text(encoding="utf-8")
        second = generate(self.root, self.out, project="demo")
        content_second = (self.out / "l1-manual-tecnico.md").read_text(encoding="utf-8")
        self.assertEqual(content_first, content_second)
        self.assertEqual(first.metrics.unsupported_claims, second.metrics.unsupported_claims)

    def test_tests_are_excluded_by_default(self) -> None:
        test_dir = self.root / "src" / "test" / "java"
        test_dir.mkdir(parents=True)
        (test_dir / "Helper.java").write_text(
            "class Helper { @GetMapping(\"/test-only\") void t() {} }", encoding="utf-8"
        )
        generate(self.root, self.out, project="demo")
        document = (self.out / "l1-manual-tecnico.md").read_text(encoding="utf-8")
        self.assertNotIn("test-only", document)

        generate(self.root, self.out, project="demo", include_tests=True)
        with_tests = (self.out / "l1-manual-tecnico.md").read_text(encoding="utf-8")
        self.assertIn("test-only", with_tests)

    def test_hard_gate_blocks_writing_when_a_fact_has_no_citation(self) -> None:
        broken = [Fact("route", "GET /x", "h", "")]
        with mock.patch("docu.generate.pipeline.java_facts", return_value=broken):
            result = generate(self.root, self.out, project="demo")
        self.assertIs(result.gate.outcome, GateOutcome.ABORT)
        self.assertEqual(result.docs, ())
        self.assertFalse(self.out.exists())

    def test_empty_repository_aborts_without_writing(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        result = generate(empty, self.out, project="empty")
        self.assertEqual(len(result.facts), 0)
        self.assertEqual(result.metrics.completeness, 0.0)
        self.assertIs(result.gate.outcome, GateOutcome.ABORT)
        self.assertEqual(result.docs, ())
        self.assertFalse(self.out.exists())

    def test_unsupported_language_is_reported_not_silently_ignored(self) -> None:
        go_repo = self.root / "goproj"
        go_repo.mkdir()
        (go_repo / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")
        result = generate(go_repo, self.out, project="goproj")
        self.assertEqual(result.unsupported_languages, {"Go": 1})
        self.assertIs(result.gate.outcome, GateOutcome.ABORT)
        self.assertIn("no soportados", result.gate.reasons[0])
        self.assertEqual(result.docs, ())

    def test_supported_and_unsupported_languages_coexist(self) -> None:
        mixed = self.root / "mixed"
        (mixed / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
        (mixed / "src" / "main" / "java" / "com" / "example" / "WidgetController.java").write_text(
            JAVA, encoding="utf-8"
        )
        (mixed / "pom.xml").write_text(POM, encoding="utf-8")
        (mixed / "worker.rs").write_text("fn main() {}\n", encoding="utf-8")
        result = generate(mixed, self.out, project="mixed")
        self.assertEqual(result.unsupported_languages, {"Rust": 1})
        self.assertTrue(result.docs)  # lo soportado sí se documenta
        document = (self.out / "l1-manual-tecnico.md").read_text(encoding="utf-8")
        self.assertIn("Rust (1)", document)

    def test_document_is_language_agnostic(self) -> None:
        """Un proyecto Python no debe describirse con vocabulario de Maven."""
        python_repo = self.root / "pyonly"
        (python_repo / "app").mkdir(parents=True)
        (python_repo / "app" / "main.py").write_text(
            "def run(x: int) -> str:\n    return str(x)\n", encoding="utf-8"
        )
        result = generate(python_repo, self.out, project="pyonly")
        document = (self.out / "l1-manual-tecnico.md").read_text(encoding="utf-8")
        self.assertNotIn("Maven", document)
        self.assertIn("run", {fact.subject for fact in result.facts})
        self.assertTrue(all("#L" in fact.citation for fact in result.facts))


if __name__ == "__main__":
    unittest.main()
