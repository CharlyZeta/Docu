"""Nivel 2: operación y despliegue, con dos garantías — nada de secretos y todo citado."""

from __future__ import annotations

import unittest

from docu.core.yamlmini import parse
from docu.generate.markdown import render_l2
from docu.generate.ops import (
    compose_facts,
    dockerfile_facts,
    env_facts,
    is_compose_file,
    is_docker_file,
    is_env_file,
    is_workflow_file,
    scripts_facts,
    workflow_facts,
)

ENV = """# Comentario que no aporta
PORT=3000
DATABASE_URL=postgres://user:supersecreto@localhost/db
API_KEY="clave-real-que-no-debe-salir"
"""

DOCKERFILE = """FROM node:20-alpine
WORKDIR /app
EXPOSE 3000 9229
CMD ["node", "server.js"]
"""

COMPOSE = """services:
  api:
    image: node:20
    ports:
      - "3000:3000"
    depends_on:
      - db
  db:
    image: postgres:16
    ports:
      - "5432:5432"
"""

WORKFLOW = """name: docu
on:
  push:
    branches: [main]
  pull_request:
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - name: Correr tests
        run: |
          python -m unittest discover -s tests -t .
          echo listo
"""


class DetectionTests(unittest.TestCase):
    def test_file_kinds(self) -> None:
        self.assertTrue(is_env_file(".env.example"))
        self.assertFalse(is_env_file(".env"))
        self.assertTrue(is_docker_file("Dockerfile"))
        self.assertTrue(is_compose_file("docker-compose.yml"))
        self.assertTrue(is_workflow_file(".github/workflows/docu.yml"))
        self.assertFalse(is_workflow_file("src/config.yml"))


class EnvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facts = env_facts(".env.example", ENV)

    def test_extracts_names_only(self) -> None:
        self.assertEqual([fact.subject for fact in self.facts], ["PORT", "DATABASE_URL", "API_KEY"])

    def test_never_copies_values(self) -> None:
        text = repr([(fact.subject, fact.detail, fact.attributes) for fact in self.facts])
        self.assertNotIn("supersecreto", text)
        self.assertNotIn("clave-real", text)
        self.assertNotIn("postgres://", text)

    def test_citation_points_to_the_line(self) -> None:
        self.assertEqual(self.facts[0].citation, ".env.example#L2-L2")

    def test_comments_are_ignored(self) -> None:
        self.assertNotIn("Comentario", " ".join(fact.subject for fact in self.facts))


class DockerfileTests(unittest.TestCase):
    def test_image_ports_and_command(self) -> None:
        facts = dockerfile_facts("Dockerfile", DOCKERFILE)
        kinds = {fact.kind for fact in facts}
        self.assertEqual(kinds, {"image", "port", "process"})
        self.assertIn("node:20-alpine", [fact.subject for fact in facts])
        self.assertEqual(
            sorted(fact.subject for fact in facts if fact.kind == "port"), ["3000", "9229"]
        )
        self.assertTrue(any(fact.subject.startswith("CMD") for fact in facts))


class ComposeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facts = compose_facts("docker-compose.yml", COMPOSE)

    def test_services(self) -> None:
        self.assertEqual(
            sorted(fact.subject for fact in self.facts if fact.kind == "service"), ["api", "db"]
        )

    def test_port_mappings(self) -> None:
        ports = sorted(fact.subject for fact in self.facts if fact.kind == "port")
        self.assertEqual(ports, ["3000→3000", "5432→5432"])

    def test_depends_on(self) -> None:
        edges = [fact.subject for fact in self.facts if fact.kind == "dependency_edge"]
        self.assertEqual(edges, ["api → db"])


class ScriptsTests(unittest.TestCase):
    def test_scripts_become_commands(self) -> None:
        source = '{"scripts": {"dev": "vite", "build": "vite build"}}'
        facts = scripts_facts("package.json", parse(source) if False else {"scripts": {"dev": "vite", "build": "vite build"}}, source)
        self.assertEqual([fact.subject for fact in facts], ["dev", "build"])
        self.assertEqual(facts[0].detail, "vite")


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facts = workflow_facts(".github/workflows/docu.yml", WORKFLOW)

    def test_workflow_name_and_jobs(self) -> None:
        self.assertIn("docu", [fact.subject for fact in self.facts if fact.kind == "workflow"])
        self.assertIn("check", [fact.subject for fact in self.facts if fact.kind == "ci_job"])

    def test_triggers(self) -> None:
        triggers = sorted(fact.subject for fact in self.facts if fact.kind == "trigger")
        self.assertEqual(triggers, ["pull_request", "push"])

    def test_block_scalar_does_not_break_parsing(self) -> None:
        payload = parse(WORKFLOW)
        self.assertIn("python -m unittest", str(payload))

    def test_malformed_yaml_is_tolerated(self) -> None:
        broken = "name: x\n  jobs:\n- mal\n    indentado: [\n"
        self.assertEqual(workflow_facts(".github/workflows/x.yml", broken), [])


class RenderTests(unittest.TestCase):
    def test_sections_and_redaction(self) -> None:
        facts = (
            env_facts(".env.example", ENV)
            + dockerfile_facts("Dockerfile", DOCKERFILE)
            + compose_facts("docker-compose.yml", COMPOSE)
            + workflow_facts(".github/workflows/docu.yml", WORKFLOW)
        )
        document = render_l2("demo", facts, {}, {})
        for section in (
            "## 1. Entorno requerido",
            "## 2. Puertos y servicios",
            "## 3. Artefactos de infraestructura",
            "## 5. Integración continua",
        ):
            self.assertIn(section, document)
        self.assertIn("`.env.example#L2-L2`", document)
        # ninguna sección puede filtrar un valor
        self.assertNotIn("supersecreto", document)
        self.assertNotIn("clave-real", document)

    def test_without_ops_facts_sections_declare_the_gap(self) -> None:
        document = render_l2("demo", (), {}, {})
        self.assertIn("Sin evidencia", document)
        self.assertIn("No** se documentan valores de secretos", document)


if __name__ == "__main__":
    unittest.main()
