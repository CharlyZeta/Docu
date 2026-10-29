"""Perfil e inicialización: la primera instalación es revisar una propuesta, no escribirla."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from docu.core.profile import (
    DEFAULT_EXCLUDE,
    Profile,
    ProfileError,
    find,
    from_dict,
    load,
    plan_changes,
    to_yaml,
)
from docu.delivery.proposal import detect, propose
from docu.delivery.cli import main
from docu.delivery.exit_codes import ExitCode

JAVA = '''package com.example;

@RestController
@RequestMapping("/v1")
public class Api {
    @GetMapping("/ping")
    public String ping() { return "pong"; }
}
'''

POM = """<project>
  <modules><module>core</module></modules>
  <dependencies>
    <dependency><groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId></dependency>
  </dependencies>
</project>
"""


def run_cli(*argv: str) -> tuple[int, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        code = main(list(argv))
    return code, buffer.getvalue()


def build_java_repo(root: Path) -> None:
    (root / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
    (root / "src" / "main" / "java" / "com" / "example" / "Api.java").write_text(JAVA, encoding="utf-8")
    (root / "pom.xml").write_text(POM, encoding="utf-8")
    (root / "application.yml").write_text("server:\n  port: 8080\n", encoding="utf-8")


class ProfileSchemaTests(unittest.TestCase):
    def test_minimal_profile_uses_documented_defaults(self) -> None:
        profile = from_dict({"project": "demo"}, fallback_project="x")
        self.assertEqual(profile.levels, ("l1", "l4"))
        self.assertEqual(profile.ttl_days, 90)
        self.assertEqual(profile.output_dir, "docs/generated")
        self.assertAlmostEqual(profile.thresholds.completeness, 9.0)
        self.assertIn("target/*", profile.effective_exclude)

    def test_profile_keeps_only_declared_exclusions(self) -> None:
        """El archivo es la verdad: los defaults se suman al usar el perfil, no al cargarlo."""
        profile = from_dict({"sources": {"git": {"exclude": ["tooling/*"]}}})
        self.assertEqual(profile.exclude, ("tooling/*",))
        self.assertIn("tooling/*", profile.effective_exclude)
        self.assertIn(DEFAULT_EXCLUDE[0], profile.effective_exclude)

    def test_new_defaults_appear_as_change_order(self) -> None:
        """Si el producto añade patrones de higiene, el perfil existente los recibe vía orden de cambio."""
        existing = from_dict({"project": "demo", "sources": {"git": {"exclude": ["solo-uno/*"]}}})
        proposed = replace(existing, exclude=DEFAULT_EXCLUDE)
        changes = plan_changes(existing, proposed)
        applied_fields = [change.field for change in changes if change.applied]
        self.assertIn("sources.git.exclude", applied_fields)

    def test_levels_are_read_from_output_block(self) -> None:
        profile = from_dict({"output": {"levels": {"l1": True, "l3": True, "l4": False}}})
        self.assertEqual(profile.levels, ("l1", "l3"))

    def test_no_level_enabled_is_an_error(self) -> None:
        with self.assertRaises(ProfileError):
            from_dict({"output": {"levels": {"l1": False, "l3": False, "l4": False}}})

    def test_invalid_mode_is_an_error(self) -> None:
        with self.assertRaises(ProfileError):
            from_dict({"mode": "yolo"})

    def test_invalid_threshold_is_an_error(self) -> None:
        with self.assertRaises(ProfileError):
            from_dict({"acceptance": {"thresholds": {"accuracy": 42}}})

    def test_non_numeric_threshold_is_an_error(self) -> None:
        with self.assertRaises(ProfileError):
            from_dict({"acceptance": {"thresholds": {"accuracy": "alto"}}})

    def test_invalid_ttl_is_an_error(self) -> None:
        with self.assertRaises(ProfileError):
            from_dict({"freshness": {"ttl_days": 0}})

    def test_glossary_is_parsed(self) -> None:
        profile = from_dict({"glossary": {"cadena de filtros": ["securityfilterchain"]}})
        self.assertEqual(profile.glossary["cadena de filtros"], ("securityfilterchain",))

    def test_ttl_and_learn_settings(self) -> None:
        profile = from_dict(
            {"freshness": {"ttl_days": 30}, "learn": {"promotion_delta": 0.2, "rollback_drop": 0.1, "federate": True}}
        )
        self.assertEqual(profile.ttl_days, 30)
        self.assertAlmostEqual(profile.promotion_delta, 0.2)
        self.assertTrue(profile.federate)

    def test_malformed_yaml_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "docu.profile.yaml"
            path.write_text("a:\n    b: 1\n  c: 2\n", encoding="utf-8")
            with self.assertRaises(ProfileError):
                load(path)

    def test_missing_profile_returns_none(self) -> None:
        self.assertIsNone(load(Path("no-existe.yaml")))


class DetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_java_repo(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_detects_language_routes_and_framework(self) -> None:
        detection = detect(self.root)
        self.assertIn("java", detection["languages"])
        self.assertEqual(detection["routes"], 1)
        self.assertIn("spring-boot", detection["frameworks"])

    def test_proposal_enables_l3_when_routes_exist(self) -> None:
        profile = propose(self.root)
        self.assertIn("l3", profile.levels)
        self.assertIn("l1", profile.levels)

    def test_proposal_seeds_glossary_for_spring(self) -> None:
        self.assertTrue(propose(self.root).glossary)

    def test_proposal_does_not_restrict_include(self) -> None:
        """Restringir por convención dejaría fuera proyectos con otra estructura."""
        self.assertEqual(propose(self.root).include, ())

    def test_proposal_roundtrips_through_yaml(self) -> None:
        profile = propose(self.root, project="demo")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "docu.profile.yaml"
            path.write_text(to_yaml(profile), encoding="utf-8")
            restored = load(path)
        assert restored is not None
        self.assertEqual(restored.project, "demo")
        self.assertEqual(restored.levels, profile.levels)
        self.assertTrue(restored.glossary)


class InitCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_java_repo(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_init_writes_profile(self) -> None:
        code, output = run_cli("init", "--root", str(self.root), "--project", "demo")
        self.assertEqual(code, int(ExitCode.OK))
        self.assertIn("escrito", output)
        self.assertTrue(find(self.root))

    def test_init_dry_run_writes_nothing(self) -> None:
        code, output = run_cli("init", "--root", str(self.root), "--dry-run")
        self.assertEqual(code, int(ExitCode.OK))
        self.assertIn("project:", output)
        self.assertIsNone(find(self.root))

    def test_init_second_run_reports_no_changes(self) -> None:
        """Reejecutar sin cambios no reescribe nada: informa y sale con 10."""
        run_cli("init", "--root", str(self.root))
        code, output = run_cli("init", "--root", str(self.root))
        self.assertEqual(code, int(ExitCode.NO_CHANGES))
        self.assertIn("sin cambios", output)

    def test_init_force_regenerates_from_scratch(self) -> None:
        run_cli("init", "--root", str(self.root))
        code, _output = run_cli("init", "--root", str(self.root), "--force")
        self.assertEqual(code, int(ExitCode.OK))


class ChangeOrderTests(unittest.TestCase):
    """La detección propone; el humano aprueba. Lo escrito a mano no se pisa."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # Repo sin rutas al inicio: el perfil se crea sin L3.
        (self.root / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
        (self.root / "src" / "main" / "java" / "com" / "example" / "Api.java").write_text(
            "package com.example;\npublic class Api {}\n", encoding="utf-8"
        )
        self.profile_path = self.root / "docu.profile.yaml"
        self.profile_path.write_text(
            "project: demo\n"
            "mode: propose\n"
            "output:\n"
            "  dir: docs\n"
            "  levels:\n"
            "    l1: true\n"
            "    l3: false\n"
            "    l4: true\n"
            "acceptance:\n"
            "  thresholds:\n"
            "    completeness: 9.5\n"
            "glossary:\n"
            '  "mi jerga": ["myterm"]\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _add_route(self) -> None:
        (self.root / "src" / "main" / "java" / "com" / "example" / "Api.java").write_text(
            JAVA, encoding="utf-8"
        )

    def test_change_order_is_proposed_but_not_applied(self) -> None:
        self._add_route()
        code, output = run_cli("init", "--root", str(self.root))
        self.assertEqual(code, int(ExitCode.NEEDS_REVIEW))
        self.assertIn("orden de cambio", output)
        self.assertIn("no se escribió nada", output)
        report = self.root / ".docu" / "init-change-order.md"
        self.assertTrue(report.exists())
        content = self.profile_path.read_text(encoding="utf-8")
        self.assertIn("l3: false", content)  # no se aplicó
        self.assertIn("mi jerga", content)  # decisión humana intacta

    def test_apply_updates_levels_and_preserves_human_fields(self) -> None:
        self._add_route()
        code, output = run_cli("init", "--root", str(self.root), "--apply")
        self.assertEqual(code, int(ExitCode.OK))
        self.assertIn("aplicada", output)
        applied = load(self.profile_path)
        assert applied is not None
        self.assertIn("l3", applied.levels)
        self.assertEqual(applied.glossary["mi jerga"], ("myterm",))
        self.assertEqual(applied.mode.value, "propose")
        self.assertAlmostEqual(applied.thresholds.completeness, 9.5)
        self.assertEqual(applied.output_dir, "docs")

    def test_dry_run_shows_change_order_and_writes_nothing(self) -> None:
        self._add_route()
        before = self.profile_path.read_text(encoding="utf-8")
        code, output = run_cli("init", "--root", str(self.root), "--dry-run")
        self.assertEqual(code, int(ExitCode.OK))
        self.assertIn("Orden de cambio", output)
        self.assertEqual(before, self.profile_path.read_text(encoding="utf-8"))
        self.assertFalse((self.root / ".docu" / "init-change-order.md").exists())

    def test_missing_hygiene_patterns_are_proposed(self) -> None:
        """Un perfil sin exclusiones recibe la propuesta de higiene, no un cambio silencioso."""
        self.profile_path.write_text(
            "project: demo\noutput:\n  levels:\n    l1: true\n    l3: true\n    l4: true\n",
            encoding="utf-8",
        )
        code, output = run_cli("init", "--root", str(self.root))
        self.assertEqual(code, int(ExitCode.NEEDS_REVIEW))
        self.assertIn("sources.git.exclude", output)
        self.assertIn("l3: true", self.profile_path.read_text(encoding="utf-8"))

    def test_profile_matching_detection_exits_no_changes(self) -> None:
        patterns = "".join(f'      - "{pattern}"\n' for pattern in DEFAULT_EXCLUDE)
        self.profile_path.write_text(
            "project: demo\n"
            "output:\n"
            "  levels:\n"
            "    l1: true\n"
            "    l3: true\n"
            "    l4: true\n"
            "sources:\n"
            "  git:\n"
            "    exclude:\n" + patterns,
            encoding="utf-8",
        )
        code, output = run_cli("init", "--root", str(self.root))
        self.assertEqual(code, int(ExitCode.NO_CHANGES))
        self.assertIn("conservad", output)


class ProfileDrivenGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_java_repo(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_generation_obeys_levels_and_output_dir(self) -> None:
        (self.root / "docu.profile.yaml").write_text(
            "project: demo\noutput:\n  dir: out-docs\n  levels:\n    l1: true\n    l3: false\n    l4: false\n",
            encoding="utf-8",
        )
        code, output = run_cli("gen", "--root", str(self.root))
        self.assertEqual(code, int(ExitCode.OK))
        self.assertIn("l1-manual-tecnico.md", output)
        produced = sorted(path.name for path in (self.root / "out-docs").glob("*.md"))
        self.assertEqual(produced, ["l1-manual-tecnico.md"])

    def test_generation_obeys_exclusions(self) -> None:
        (self.root / "tooling").mkdir()
        (self.root / "tooling" / "helper.rs").write_text("fn main() {}", encoding="utf-8")
        (self.root / "docu.profile.yaml").write_text(
            'project: demo\nsources:\n  git:\n    exclude: ["tooling/*"]\n', encoding="utf-8"
        )
        _code, output = run_cli("gen", "--root", str(self.root))
        self.assertNotIn("Rust", output)

    def test_invalid_profile_returns_config_error(self) -> None:
        (self.root / "docu.profile.yaml").write_text("mode: yolo\n", encoding="utf-8")
        code, output = run_cli("gen", "--root", str(self.root))
        self.assertEqual(code, int(ExitCode.CONFIG_ERROR))
        self.assertIn("perfil inválido", output)

    def test_status_uses_profile_levels(self) -> None:
        (self.root / "docu.profile.yaml").write_text(
            "project: demo\noutput:\n  levels:\n    l1: true\n    l3: false\n    l4: false\n", encoding="utf-8"
        )
        run_cli("gen", "--root", str(self.root))
        code, output = run_cli("status", "--root", str(self.root), "--json")
        self.assertEqual(code, int(ExitCode.OK))
        self.assertIn('"l1": "fresh"', output)
        self.assertNotIn('"l4"', output)

    def test_cli_flag_overrides_profile_levels(self) -> None:
        (self.root / "docu.profile.yaml").write_text(
            "project: demo\noutput:\n  levels:\n    l1: true\n    l4: false\n", encoding="utf-8"
        )
        code, output = run_cli("gen", "--root", str(self.root), "--level", "l4")
        self.assertEqual(code, int(ExitCode.OK))
        self.assertIn("l4-readme.md", output)


if __name__ == "__main__":
    unittest.main()
