"""El README no puede mentir: si menciona un comando, una herramienta o un número, es cierto.

Esta guardia existe porque un README desactualizado es peor que ninguno: describe un producto que ya
no existe. Cada commit que cambie capacidades debería actualizarlo, y el CI lo verifica en lugar de
confiar en la disciplina de quien escribe.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"


def readme_text() -> str:
    return README.read_text(encoding="utf-8")


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        from docu.delivery.cli import _build_parser

        self.parser = _build_parser()
        parser = self.parser
        actions = [action for action in parser._actions if action.dest == "command"]
        self.subcommands = set(actions[0].choices or {}) if actions else set()

    def test_every_documented_command_exists(self) -> None:
        """`docu <cmd>` en el README debe ser un subcomando real."""
        mentioned = set(re.findall(r"(?m)^\s*docu\s+([a-z_-]+)", readme_text()))
        mentioned |= set(re.findall(r"`docu ([a-z_-]+)", readme_text()))
        # Los flags (--version, --help) no son subcomandos.
        unknown = {
            name
            for name in mentioned
            if name not in self.subcommands and not name.startswith("-")
        }
        self.assertFalse(
            unknown,
            msg=f"el README menciona comandos inexistentes: {sorted(unknown)}. "
            f"Disponibles: {sorted(self.subcommands)}",
        )


class McpToolTests(unittest.TestCase):
    def test_documented_tools_match_the_server(self) -> None:
        from docu.delivery.mcp_server import READ_ONLY_TOOLS

        text = readme_text()
        documented = set(re.findall(r"`([a-z_]+)`", text))
        for tool in READ_ONLY_TOOLS:
            self.assertIn(tool, documented, msg=f"falta documentar la herramienta {tool}")
        # Toda herramienta con forma de tool MCP que aparezca en el README debe existir.
        suspicious = {
            name
            for name in documented
            if name.startswith(("get_", "list_", "search_", "verify_")) and name not in READ_ONLY_TOOLS
        }
        self.assertFalse(suspicious, msg=f"el README documenta herramientas inexistentes: {suspicious}")


class ExitCodeTests(unittest.TestCase):
    def test_documented_codes_exist(self) -> None:
        from docu.delivery.exit_codes import ExitCode

        known = {int(code) for code in ExitCode}
        text = readme_text()
        block = text.split("## Códigos de salida", 1)[1].split("##", 1)[0]
        documented = {int(number) for number in re.findall(r"(?m)^\|\s*(\d+)\s*\|", block)}
        self.assertTrue(documented, msg="la tabla de códigos de salida desapareció")
        self.assertFalse(
            documented - known, msg=f"el README documenta códigos inexistentes: {documented - known}"
        )


class AssetTests(unittest.TestCase):
    """La cabecera del README: toda imagen local tiene que existir y pesar lo razonable."""

    def setUp(self) -> None:
        self.raiz = Path(__file__).resolve().parent.parent
        self.texto = (self.raiz / "README.md").read_text(encoding="utf-8")

    def test_local_images_exist(self) -> None:
        import re

        for ruta in re.findall(r"<img[^>]+src=\"([^\"]+)\"", self.texto):
            if ruta.startswith(("http://", "https://")):
                continue
            self.assertTrue((self.raiz / ruta).is_file(), f"la imagen {ruta} no existe")

    def test_cover_is_present_and_not_heavy(self) -> None:
        portada = self.raiz / "docs" / "brand" / "portada.png"
        self.assertTrue(portada.is_file())
        self.assertIn("docs/brand/portada.png", self.texto)
        self.assertLess(portada.stat().st_size, 1_500_000, "la portada pesa demasiado para un README")

    def test_cover_has_alt_text(self) -> None:
        self.assertIn("alt=\"docu:", self.texto)

    def test_video_is_linked_with_its_limit_explained(self) -> None:
        self.assertIn("Docu.mp4", self.texto)
        self.assertIn("editor web de GitHub", self.texto)


class VersionTests(unittest.TestCase):
    def test_version_reports_path_and_command_count(self) -> None:
        """Sin la ruta y el número de comandos no se puede detectar un binario viejo."""
        from docu.delivery.cli import _version_text

        text = _version_text(14)
        self.assertIn("docu 0.1.0", text)
        self.assertIn("schema", text)
        self.assertIn("14 comandos", text)
        self.assertIn("docu", text.split("·")[-1])

    def test_unknown_command_explains_a_stale_install(self) -> None:
        import contextlib
        import io

        from docu.delivery.cli import _build_parser

        parser = _build_parser()
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer), self.assertRaises(SystemExit):
            parser.parse_args(["comando-que-no-existe"])
        message = buffer.getvalue()
        self.assertIn("uv tool install --force", message)
        self.assertIn("--version", message)


class NumberTests(unittest.TestCase):
    def test_test_count_matches_reality(self) -> None:
        """El badge de tests no puede quedarse atrás.

        Se cuenta con el mismo loader que usa el runner: el número del badge tiene que ser el que
        imprime `python -m unittest`.
        """
        loader = unittest.TestLoader()
        suite = loader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
        actual = suite.countTestCases()
        match = re.search(r"tests-(\d+)", readme_text())
        self.assertIsNotNone(match, msg="falta el badge de tests en el README")
        claimed = int(match.group(1))
        self.assertEqual(
            claimed,
            actual,
            msg=f"el README dice {claimed} tests y hay {actual}: actualizá el badge",
        )

    def test_badges_point_to_the_real_repository(self) -> None:
        from docu.delivery import cli as cli_module

        self.assertIn("github.com/CharlyZeta/Docu", readme_text())
        text = cli_module.__doc__ or ""
        self.assertNotIn("TODO", text)

    def test_no_stale_placeholders(self) -> None:
        text = readme_text()
        for placeholder in ("TODO", "FIXME", "XXX", "pendiente de completar"):
            self.assertNotIn(placeholder, text, msg=f"placeholder en el README: {placeholder}")


if __name__ == "__main__":
    unittest.main()
