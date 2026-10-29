"""Aprendizaje entre instalaciones: ledger, promoción con reversión y federación anónima."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from docu.core.contracts import GateDecision, GateOutcome, Metrics
from docu.delivery.cli import main
from docu.delivery.exit_codes import ExitCode
from docu.learn import federation, ledger, patterns, promotion
from docu.learn.patterns import Candidate, Pattern, PatternLibrary

JAVA = '''@RestController
@RequestMapping("/api")
public class Api {
    @GetMapping("/ping")
    public String ping() { return "pong"; }
}
'''


def run_cli(*argv: str) -> tuple[int, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        code = main(list(argv))
    return code, buffer.getvalue()


def build_repo(root: Path) -> None:
    (root / "src" / "main" / "java").mkdir(parents=True)
    (root / "src" / "main" / "java" / "Api.java").write_text(JAVA, encoding="utf-8")
    (root / "pom.xml").write_text(
        "<project><modules><module>core</module></modules></project>", encoding="utf-8"
    )
    (root / "application.yml").write_text("server:\n  port: 8080\n", encoding="utf-8")


def metrics(**overrides: float) -> Metrics:
    base: dict[str, float] = dict(
        accuracy=9.0,
        completeness=9.0,
        attribution=9.5,
        conciseness=8.0,
        freshness=10.0,
        cost_usd=0.0,
        unsupported_claims=0,
    )
    base.update(overrides)
    return Metrics(**base)  # type: ignore[arg-type]


class LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / ".docu" / "ledger.jsonl"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_append_and_load(self) -> None:
        record = ledger.append(
            self.path,
            project="demo",
            metrics=metrics(),
            gate=GateDecision(GateOutcome.PUBLISH),
            states={"l1": "stale"},
            versions={"docu": "0.1.0"},
        )
        self.assertTrue(record.run_id.startswith("run-"))
        loaded = ledger.load(self.path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["project"], "demo")

    def test_summary(self) -> None:
        for value in (9.0, 8.0):
            ledger.append(
                self.path,
                project="demo",
                metrics=metrics(completeness=value),
                gate=GateDecision(GateOutcome.PUBLISH),
            )
        summary = ledger.summarize(ledger.load(self.path))
        self.assertEqual(summary["runs"], 2)
        self.assertAlmostEqual(summary["metrics"]["completeness"], 8.5)  # type: ignore[index]
        self.assertEqual(summary["aborted"], 0)

    def test_corrupt_lines_are_ignored(self) -> None:
        ledger.append(self.path, project="demo", metrics=metrics(), gate=GateDecision(GateOutcome.PUBLISH))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("{esto no es json\n")
        self.assertEqual(len(ledger.load(self.path)), 1)

    def test_empty_ledger_summary(self) -> None:
        self.assertEqual(ledger.summarize([])["runs"], 0)

    def test_outcome_counts(self) -> None:
        ledger.append(self.path, project="demo", metrics=metrics(), gate=GateDecision(GateOutcome.PUBLISH))
        ledger.append(self.path, project="demo", metrics=metrics(), gate=GateDecision(GateOutcome.REVIEW))
        self.assertEqual(ledger.outcome_counts(ledger.load(self.path)), {"publish": 1, "review": 1})


class PatternTests(unittest.TestCase):
    def _pattern(self, completeness: float = 9.0) -> Pattern:
        return Pattern(
            pattern_id="java:profile_default",
            stack="java",
            kind="profile_default",
            metrics={"accuracy": 9.0, "completeness": completeness, "attribution": 9.5, "conciseness": 8.0},
            runs=3,
        )

    def test_promote_records_history(self) -> None:
        library = PatternLibrary()
        library.promote(self._pattern())
        self.assertEqual(library.version, "1")
        self.assertIn("java:profile_default", library.patterns)
        self.assertEqual(library.history[0]["action"], "promote")

    def test_revert_restores_previous(self) -> None:
        library = PatternLibrary()
        library.promote(self._pattern(9.0))
        library.promote(self._pattern(7.0))
        self.assertEqual(library.patterns["java:profile_default"].metrics["completeness"], 7.0)
        self.assertTrue(library.revert("java:profile_default"))
        self.assertEqual(library.patterns["java:profile_default"].metrics["completeness"], 9.0)

    def test_revert_without_history_returns_false(self) -> None:
        self.assertFalse(PatternLibrary().revert("no-existe"))

    def test_roundtrip(self) -> None:
        library = PatternLibrary()
        library.promote(self._pattern())
        with tempfile.TemporaryDirectory() as tmp:
            path = library.save(Path(tmp) / "patterns.json")
            restored = PatternLibrary.load(path)
        self.assertEqual(restored.version, library.version)
        self.assertIn("java:profile_default", restored.patterns)

    def test_candidates_group_by_project(self) -> None:
        records = [
            {"project": "demo", "metrics": {"completeness": 9.0, "conciseness": 8.0}, "versions": {"languages": "java"}},
            {"project": "demo", "metrics": {"completeness": 7.0, "conciseness": 8.0}, "versions": {"languages": "java"}},
        ]
        candidates = patterns.candidates_from(records)
        self.assertEqual(len(candidates), 1)
        self.assertAlmostEqual(candidates[0].pattern.metrics["completeness"], 8.0)
        self.assertEqual(candidates[0].pattern.runs, 2)


class DecisionTests(unittest.TestCase):
    def _current(self) -> Pattern:
        return Pattern("java:p", "java", "profile_default", {"accuracy": 8.0, "completeness": 8.0, "attribution": 8.0, "conciseness": 8.0})

    def test_first_promotes(self) -> None:
        decision = promotion.decide(None, self._current())
        self.assertEqual(decision.action, promotion.PROMOTE)

    def test_better_candidate_promotes(self) -> None:
        candidate = Pattern("java:p", "java", "profile_default", {"accuracy": 9.0, "completeness": 9.0, "attribution": 9.0, "conciseness": 9.0})
        self.assertEqual(promotion.decide(self._current(), candidate).action, promotion.PROMOTE)

    def test_tiny_improvement_is_rejected(self) -> None:
        candidate = Pattern("java:p", "java", "profile_default", {"accuracy": 8.01, "completeness": 8.01, "attribution": 8.01, "conciseness": 8.01})
        decision = promotion.decide(self._current(), candidate, promotion_delta=0.05)
        self.assertEqual(decision.action, promotion.REJECT)

    def test_regression_forces_rollback(self) -> None:
        candidate = Pattern("java:p", "java", "profile_default", {"accuracy": 9.0, "completeness": 7.0, "attribution": 9.0, "conciseness": 9.0})
        decision = promotion.decide(self._current(), candidate, rollback_drop=0.05)
        self.assertEqual(decision.action, promotion.ROLLBACK)
        self.assertIn("degrada", decision.reasons[0])

    def test_describe_is_human_readable(self) -> None:
        decision = promotion.decide(None, self._current())
        self.assertIn("PROMOTE", decision.describe())


class FederationTests(unittest.TestCase):
    def _library(self) -> PatternLibrary:
        library = PatternLibrary()
        library.promote(
            Pattern(
                "cliente-secreto:java:profile_default",
                "java",
                "profile_default",
                {"accuracy": 9.0, "completeness": 9.5},
                runs=4,
            )
        )
        return library

    def test_payload_has_no_client_identifiers(self) -> None:
        payload = federation.build_payload(self._library())
        text = payload.to_json()
        self.assertNotIn("cliente-secreto", text)
        self.assertIn("fp_", text)

    def test_payload_keys_are_whitelisted(self) -> None:
        payload = federation.build_payload(self._library())
        self.assertLessEqual(set(payload.data), federation.ALLOWED_KEYS)
        for pattern in payload.data["patterns"]:  # type: ignore[index]
            self.assertLessEqual(set(pattern), federation.ALLOWED_KEYS)

    def test_paths_are_rejected(self) -> None:
        with self.assertRaises(federation.FederationError):
            federation.assert_anonymous({"schema_version": "1.0", "patterns": [{"stack": "C:\\repo\\x"}]})

    def test_disallowed_key_is_rejected(self) -> None:
        with self.assertRaises(federation.FederationError):
            federation.assert_anonymous({"schema_version": "1.0", "project": "cliente"})

    def test_send_dry_run_does_not_network(self) -> None:
        payload = federation.build_payload(self._library())
        result = federation.send(payload, "https://example.invalid/x", dry_run=True)
        self.assertFalse(result["sent"])
        self.assertEqual(result["reason"], "dry-run")

    def test_send_without_endpoint_reports_reason(self) -> None:
        payload = federation.build_payload(self._library())
        result = federation.send(payload, None, dry_run=False)
        self.assertFalse(result["sent"])
        self.assertEqual(result["reason"], "sin endpoint configurado")

    def test_bad_endpoint_is_rejected(self) -> None:
        payload = federation.build_payload(self._library())
        with self.assertRaises(federation.FederationError):
            federation.send(payload, "ftp://example.com", dry_run=False)

    def test_fingerprint_is_stable(self) -> None:
        self.assertEqual(federation.fingerprint("a"), federation.fingerprint("a"))
        self.assertNotEqual(federation.fingerprint("a"), federation.fingerprint("b"))


class CliLearnTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_repo(self.root)
        self.out = str(self.root / "docs" / "generated")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_generation_feeds_the_ledger(self) -> None:
        run_cli("gen", "--root", str(self.root), "--out", self.out, "--project", "demo")
        self.assertTrue((self.root / ".docu" / "ledger.jsonl").exists())
        code, output = run_cli("learn", "--root", str(self.root))
        self.assertEqual(code, int(ExitCode.OK))
        self.assertIn("1 corridas", output)
        self.assertIn("candidato", output)

    def test_empty_ledger_returns_no_changes(self) -> None:
        code, output = run_cli("learn", "--root", str(self.root))
        self.assertEqual(code, int(ExitCode.NO_CHANGES))
        self.assertIn("0 corridas", output)

    def test_promote_writes_library(self) -> None:
        run_cli("gen", "--root", str(self.root), "--out", self.out, "--project", "demo")
        code, output = run_cli("learn", "--root", str(self.root), "--promote")
        self.assertEqual(code, int(ExitCode.OK))
        self.assertIn("biblioteca de patrones", output)
        self.assertTrue((self.root / ".docu" / "patterns.json").exists())

    def test_promote_second_time_is_no_changes(self) -> None:
        run_cli("gen", "--root", str(self.root), "--out", self.out, "--project", "demo")
        run_cli("learn", "--root", str(self.root), "--promote")
        code, _output = run_cli("learn", "--root", str(self.root), "--promote")
        self.assertEqual(code, int(ExitCode.NO_CHANGES))

    def test_federate_dry_run_prints_payload_and_sends_nothing(self) -> None:
        run_cli("gen", "--root", str(self.root), "--out", self.out, "--project", "demo")
        run_cli("learn", "--root", str(self.root), "--promote")
        code, output = run_cli("learn", "--root", str(self.root), "--federate", "--dry-run")
        self.assertEqual(code, int(ExitCode.OK))
        payload = json.loads(output.split("federación:")[0])
        self.assertIn("patterns", payload)
        self.assertIn("no enviado", output)

    def test_federate_json_is_machine_readable(self) -> None:
        run_cli("learn", "--root", str(self.root), "--federate", "--dry-run", "--json")
        lines = output = run_cli("learn", "--root", str(self.root), "--federate", "--dry-run", "--json")[1]
        first = lines.strip().splitlines()[0]
        self.assertTrue(first.startswith("{"))


class CandidateTests(unittest.TestCase):
    def test_candidate_key(self) -> None:
        candidate = Candidate(pattern=Pattern("java:p", "java", "profile_default"))
        self.assertEqual(candidate.key, "java:p")


if __name__ == "__main__":
    unittest.main()
