"""`.gitignore` como fuente de verdad: si el proyecto lo ignora, docu no lo documenta."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docu.index.ignore import is_ignored, load, parse


def ignored(rel: str, text: str, is_dir: bool = False) -> bool:
    return is_ignored(rel, parse(text), is_dir=is_dir)


class ParseTests(unittest.TestCase):
    def test_comments_and_blank_lines_are_skipped(self) -> None:
        self.assertEqual(parse("# comentario\n\n   \n"), [])

    def test_negation_and_directory_marker(self) -> None:
        rules = parse("!coverage/\n")
        self.assertTrue(rules[0].negate)
        self.assertTrue(rules[0].directory_only)


class MatchTests(unittest.TestCase):
    def test_plain_name_matches_at_any_depth(self) -> None:
        self.assertTrue(ignored("a/b/coverage/x.js", "coverage\n"))
        self.assertTrue(ignored("coverage/x.js", "coverage/", is_dir=True))

    def test_directory_pattern_covers_its_contents(self) -> None:
        self.assertTrue(ignored("coverage/block-navigation.js", "coverage/\n"))

    def test_anchored_pattern_only_matches_from_root(self) -> None:
        self.assertTrue(ignored("docs/generated/x.md", "/docs/generated/\n"))
        self.assertFalse(ignored("src/docs/generated/x.md", "/docs/generated/\n"))

    def test_double_star(self) -> None:
        self.assertTrue(ignored("a/b/c/reporte.json", "**/reporte.json\n"))
        self.assertTrue(ignored("dist/app.js", "dist/**\n"))

    def test_extension_pattern(self) -> None:
        self.assertTrue(ignored("logs/app.log", "*.log\n"))
        self.assertFalse(ignored("src/app.py", "*.log\n"))

    def test_negation_reincludes(self) -> None:
        rules = parse("*.log\n!importante.log\n")
        self.assertTrue(is_ignored("app.log", rules))
        self.assertFalse(is_ignored("importante.log", rules))

    def test_last_rule_wins(self) -> None:
        rules = parse("!*.log\n*.log\n")
        self.assertTrue(is_ignored("app.log", rules))

    def test_unrelated_path_is_not_ignored(self) -> None:
        self.assertFalse(ignored("src/app.ts", "coverage/\ndist/\n"))


class LoadTests(unittest.TestCase):
    def test_missing_gitignore_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load(Path(tmp)), [])

    def test_reads_the_project_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("graphify-out/\nbackups/\n", encoding="utf-8")
            rules = load(root)
            self.assertTrue(is_ignored("graphify-out/x.json", rules))
            self.assertFalse(is_ignored("src/app.ts", rules))


class PipelineTests(unittest.TestCase):
    """El síntoma que reportó un proyecto real: `coverage/` contado como código."""

    def test_coverage_is_excluded_without_a_profile(self) -> None:
        from docu.generate.pipeline import collect_facts

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.ts").write_text("export class App {}\n", encoding="utf-8")
            (root / "coverage").mkdir()
            (root / "coverage" / "block-navigation.js").write_text("var x = 1;\n", encoding="utf-8")
            facts, sources = collect_facts(root)
            self.assertNotIn("coverage/block-navigation.js", sources)
            self.assertIn("src/app.ts", sources)

    def test_project_gitignore_is_respected(self) -> None:
        from docu.generate.pipeline import collect_facts

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("mirror-cliente/\nartefactos/\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "app.ts").write_text("export class App {}\n", encoding="utf-8")
            (root / "mirror-cliente").mkdir()
            (root / "mirror-cliente" / "legacy.php").write_text("<?php echo 1;\n", encoding="utf-8")
            facts, sources = collect_facts(root)
            self.assertNotIn("mirror-cliente/legacy.php", sources)
            self.assertEqual(sources.get("src/app.ts") is not None, True)

    def test_unsupported_languages_also_respect_gitignore(self) -> None:
        from docu.generate.pipeline import unsupported_sources

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("mirror/\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "app.ts").write_text("export class App {}\n", encoding="utf-8")
            (root / "mirror").mkdir()
            (root / "mirror" / "a.php").write_text("<?php\n", encoding="utf-8")
            (root / "src" / "b.php").write_text("<?php\n", encoding="utf-8")
            counts = unsupported_sources(root)
            self.assertEqual(counts.get(".php"), 1)  # sólo el de src, no el del mirror


class PackageCitationTests(unittest.TestCase):
    def test_directory_package_cites_the_whole_file_and_says_why(self) -> None:
        from docu.index.packages import detect_packages

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "src" / "components"
            folder.mkdir(parents=True)
            for index in range(3):
                (folder / f"c{index}.tsx").write_text(
                    "\n".join(f"// linea {row}" for row in range(1, 12)) + "\n", encoding="utf-8"
                )
            files = {path.relative_to(root).as_posix(): path for path in root.rglob("*.tsx")}
            packages = {package.name: package for package in detect_packages(files)}
            package = packages["src.components"]
            self.assertEqual(package.language, "typescript (directorio)")
            self.assertRegex(package.citation, r"#L1-L1[12]$")


if __name__ == "__main__":
    unittest.main()
