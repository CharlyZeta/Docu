"""Los README no pueden mentir: si mencionan un comando, una herramienta o un número, es cierto.

Existen dos versiones (inglés y español) y la guardia cubre **las dos**: un README desactualizado es
peor que ninguno, y una traducción que se queda atrás lo es todavía más, porque nadie la revisa.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README_EN = ROOT / "README.md"
README_ES = ROOT / "README.es.md"
READMES = {"inglés": README_EN, "español": README_ES}


def readme_text() -> str:
    return README_EN.read_text(encoding="utf-8")


def texts() -> dict[str, str]:
    return {nombre: ruta.read_text(encoding="utf-8") for nombre, ruta in READMES.items()}


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        from docu.delivery.cli import _build_parser

        parser = _build_parser()
        actions = [action for action in parser._actions if action.dest == "command"]
        self.subcommands = set(actions[0].choices or {}) if actions else set()

    def test_every_documented_command_exists(self) -> None:
        """`docu <cmd>` en cualquiera de las dos versiones debe ser un subcomando real."""
        for idioma, texto in texts().items():
            with self.subTest(idioma=idioma):
                mentioned = set(re.findall(r"(?m)^\s*docu\s+([a-z_-]+)", texto))
                mentioned |= set(re.findall(r"`docu ([a-z_-]+)", texto))
                # Los flags (`--version`, `--help`) no son subcomandos.
                unknown = {
                    name
                    for name in mentioned
                    if name not in self.subcommands and not name.startswith("-")
                }
                self.assertFalse(
                    unknown,
                    msg=f"el README en {idioma} menciona comandos inexistentes: {sorted(unknown)}. "
                    f"Disponibles: {sorted(self.subcommands)}",
                )


class McpToolTests(unittest.TestCase):
    def test_documented_tools_match_the_server(self) -> None:
        from docu.delivery.mcp_server import READ_ONLY_TOOLS

        for idioma, texto in texts().items():
            with self.subTest(idioma=idioma):
                documented = set(re.findall(r"`([a-z_]+)`", texto))
                for tool in READ_ONLY_TOOLS:
                    self.assertIn(tool, documented, msg=f"falta {tool} en el README en {idioma}")
                suspicious = {
                    name
                    for name in documented
                    if name.startswith(("get_", "list_", "search_", "verify_"))
                    and name not in READ_ONLY_TOOLS
                }
                self.assertFalse(
                    suspicious, msg=f"herramientas inexistentes en {idioma}: {suspicious}"
                )


class ExitCodeTests(unittest.TestCase):
    HEADINGS = ("## Exit codes", "## Códigos de salida")

    def test_documented_codes_exist(self) -> None:
        from docu.delivery.exit_codes import ExitCode

        known = {int(code) for code in ExitCode}
        for idioma, texto in texts().items():
            with self.subTest(idioma=idioma):
                heading = next((name for name in self.HEADINGS if name in texto), None)
                self.assertIsNotNone(heading, msg=f"falta la tabla de códigos en {idioma}")
                block = texto.split(heading, 1)[1].split("##", 1)[0]
                documented = {
                    int(number) for number in re.findall(r"(?m)^\|\s*(\d+)\s*\|", block)
                }
                self.assertTrue(documented, msg=f"la tabla de códigos desapareció en {idioma}")
                self.assertFalse(
                    documented - known,
                    msg=f"el README en {idioma} documenta códigos inexistentes: {documented - known}",
                )


class AssetTests(unittest.TestCase):
    """La cabecera: toda imagen local tiene que existir y pesar lo razonable."""

    def test_local_images_exist(self) -> None:
        for idioma, texto in texts().items():
            for ruta in re.findall(r"<img[^>]+src=\"([^\"]+)\"", texto):
                if ruta.startswith(("http://", "https://")):
                    continue
                with self.subTest(idioma=idioma, ruta=ruta):
                    self.assertTrue((ROOT / ruta).is_file(), f"la imagen {ruta} no existe")

    def test_cover_is_present_and_not_heavy(self) -> None:
        portada = ROOT / "docs" / "brand" / "portada.png"
        self.assertTrue(portada.is_file())
        for idioma, texto in texts().items():
            self.assertIn("docs/brand/portada.png", texto, msg=f"falta la portada en {idioma}")
        self.assertLess(portada.stat().st_size, 1_500_000, "la portada pesa demasiado para un README")

    def test_cover_has_alt_text_in_both_languages(self) -> None:
        for idioma, texto in texts().items():
            self.assertIn('alt="docu:', texto, msg=f"falta el texto alternativo en {idioma}")

    def test_no_video_references(self) -> None:
        """El video no se puede reproducir desde el repo: no se anuncia lo que no se ve."""
        for idioma, texto in texts().items():
            with self.subTest(idioma=idioma):
                self.assertNotIn(".mp4", texto)
                self.assertNotIn("<video", texto)


class LanguageTests(unittest.TestCase):
    def test_both_readmes_link_to_each_other(self) -> None:
        ingles = readme_text()
        self.assertTrue(
            "README.es.md" in ingles and ("[Español]" in ingles or 'href="README.es.md"' in ingles),
            msg="el README en inglés no enlaza la versión en español",
        )
        espanol = README_ES.read_text(encoding="utf-8")
        self.assertTrue(
            "README.md" in espanol and ("[English]" in espanol or 'href="README.md"' in espanol),
            msg="el README en español no enlaza la versión en inglés",
        )

    def test_both_readmes_carry_the_same_badges(self) -> None:
        """Una traducción que arrastra números viejos es peor que no tener traducción."""
        contadores = {
            idioma: re.search(r"tests-(\d+)", texto).group(1)  # type: ignore[union-attr]
            for idioma, texto in texts().items()
        }
        self.assertEqual(len(set(contadores.values())), 1, msg=f"badges distintos: {contadores}")

    def test_english_readme_is_the_default(self) -> None:
        self.assertIn("# docu", readme_text())
        self.assertIn("Technical documentation you can verify", readme_text())


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
        """El badge de tests no puede quedarse atrás, en ninguna de las dos versiones."""
        loader = unittest.TestLoader()
        suite = loader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
        actual = suite.countTestCases()
        for idioma, texto in texts().items():
            with self.subTest(idioma=idioma):
                match = re.search(r"tests-(\d+)", texto)
                self.assertIsNotNone(match, msg=f"falta el badge de tests en {idioma}")
                claimed = int(match.group(1))  # type: ignore[union-attr]
                self.assertEqual(
                    claimed,
                    actual,
                    msg=f"el README en {idioma} dice {claimed} tests y hay {actual}",
                )

    def test_badges_point_to_the_real_repository(self) -> None:
        for idioma, texto in texts().items():
            self.assertIn("github.com/CharlyZeta/Docu", texto, msg=f"falta el repo en {idioma}")

    def test_no_stale_placeholders(self) -> None:
        for idioma, texto in texts().items():
            for placeholder in ("TODO", "FIXME", "XXX", "pendiente de completar"):
                self.assertNotIn(placeholder, texto, msg=f"placeholder en {idioma}: {placeholder}")


if __name__ == "__main__":
    unittest.main()
