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
        unknown = {name for name in mentioned if name not in self.subcommands and name != "--help"}
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
