"""El CI también se prueba: si un workflow pierde un paso, esto falla antes que el runner.

Un workflow roto no avisa: se queda en verde porque el paso que verificaba algo ya no está, o en rojo
para siempre porque nadie lo mira. Estas comprobaciones usan el propio `yamlmini` del proyecto.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from docu.core.yamlmini import parse

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"


def cargar(nombre: str) -> dict:
    return parse((WORKFLOWS / nombre).read_text(encoding="utf-8"))


def pasos(job: dict) -> str:
    """Todo el texto de los pasos de un job, para buscar comandos sin depender de la forma exacta."""
    partes: list[str] = []
    for step in job.get("steps") or []:
        for clave in ("name", "run", "uses"):
            valor = step.get(clave)
            if isinstance(valor, str):
                partes.append(valor)
            elif isinstance(valor, dict):
                partes.extend(str(item) for item in valor.values())
    return "\n".join(partes)


class CiWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = cargar("ci.yml")

    def test_runs_the_full_suite_on_more_than_one_os(self) -> None:
        job = self.workflow["jobs"]["test"]
        matriz = job["strategy"]["matrix"]
        self.assertIn("ubuntu-latest", matriz["os"])
        self.assertIn("windows-latest", matriz["os"], msg="Windows es donde aparecen los CRLF")
        self.assertIn("3.11", matriz["python"], msg="el mínimo declarado tiene que probarse")
        self.assertIn("3.13", matriz["python"])
        self.assertIn("unittest discover", pasos(job))

    def test_lint_gate_runs_the_project_rule_set(self) -> None:
        """La compuerta usa el conjunto completo del proyecto, con la versión fijada."""
        texto = pasos(self.workflow["jobs"]["lint"])
        self.assertIn("ruff check src tests", texto)
        self.assertNotIn("--select", texto, msg="el conjunto de reglas vive en pyproject.toml")
        self.assertIn("ruff~=", texto, msg="una regla nueva de una versión futura rompería PRs ajenos")

    def test_packaging_installs_the_wheel(self) -> None:
        texto = pasos(self.workflow["jobs"]["packaging"])
        self.assertIn("python -m build", texto)
        self.assertIn(".whl", texto)
        self.assertIn("upload-artifact", texto)


class DocuWorkflowTests(unittest.TestCase):
    def test_freshness_gate_and_regen_exist(self) -> None:
        workflow = cargar("docu.yml")
        self.assertIn("docu ci check", pasos(workflow["jobs"]["check"]))
        self.assertIn("docu ci regen", pasos(workflow["jobs"]["regen"]))

    def test_regen_does_not_fail_when_pr_creation_is_blocked(self) -> None:
        """GitHub trae apagada la creación de PRs por Actions: la rama se publica igual."""
        texto = pasos(cargar("docu.yml")["jobs"]["regen"])
        self.assertIn("git push", texto)
        self.assertIn("gh pr create", texto)
        self.assertIn("::warning::", texto)


class PagesWorkflowTests(unittest.TestCase):
    def test_generates_audits_and_deploys(self) -> None:
        workflow = cargar("pages.yml")
        build = pasos(workflow["jobs"]["build"])
        self.assertIn("docu gen", build)
        self.assertIn("docu audit", build, msg="no se publica documentación sin auditar")
        self.assertIn("--min-score", build)
        self.assertIn("docu site", build)
        self.assertIn(".nojekyll", build)
        self.assertIn("upload-pages-artifact", build)
        self.assertIn("actions/deploy-pages", pasos(workflow["jobs"]["deploy"]))

    def test_build_is_required_before_deploy(self) -> None:
        workflow = cargar("pages.yml")
        self.assertEqual(workflow["jobs"]["deploy"]["needs"], "build")


class CommandExistenceTests(unittest.TestCase):
    def test_every_docu_command_in_the_workflows_exists(self) -> None:
        import re

        from docu.delivery.cli import _build_parser

        parser = _build_parser()
        acciones = [action for action in parser._actions if action.dest == "command"]
        disponibles = set(acciones[0].choices or {}) if acciones else set()
        for ruta in sorted(WORKFLOWS.glob("*.yml")):
            texto = ruta.read_text(encoding="utf-8")
            for nombre in set(re.findall(r"docu ([a-z_-]+)", texto)):
                if nombre.startswith("-"):
                    continue  # `docu --version` es un flag, no un subcomando
                with self.subTest(workflow=ruta.name, comando=nombre):
                    self.assertIn(nombre, disponibles, msg=f"{ruta.name} usa `docu {nombre}`")


if __name__ == "__main__":
    unittest.main()
