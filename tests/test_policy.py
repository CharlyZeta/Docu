"""Compuertas: la autonomia se demuestra aqui, no en la prosa del README."""

from __future__ import annotations

import unittest

from docu.core.contracts import GateOutcome, Metrics, Mode
from docu.core.policy import Budget, BudgetExhausted, GatePolicy, Thresholds


def _metrics(**overrides: float | int) -> Metrics:
    base: dict[str, float | int] = dict(
        accuracy=9.0,
        completeness=9.5,
        attribution=9.8,
        conciseness=8.0,
        freshness=10.0,
        cost_usd=0.4,
        unsupported_claims=0,
    )
    base.update(overrides)
    return Metrics(**base)  # type: ignore[arg-type]


class GatePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = GatePolicy(thresholds=Thresholds())

    def test_good_document_publishes_in_apply_mode(self) -> None:
        decision = self.policy.evaluate(_metrics(), Mode.APPLY)
        self.assertIs(decision.outcome, GateOutcome.PUBLISH)
        self.assertEqual(decision.reasons, ())

    def test_unsupported_claim_aborts(self) -> None:
        decision = self.policy.evaluate(_metrics(unsupported_claims=2), Mode.APPLY)
        self.assertIs(decision.outcome, GateOutcome.ABORT)
        self.assertFalse(decision.may_write)

    def test_low_metric_only_opens_review(self) -> None:
        decision = self.policy.evaluate(_metrics(accuracy=7.9), Mode.APPLY)
        self.assertIs(decision.outcome, GateOutcome.REVIEW)
        self.assertTrue(decision.may_write)
        self.assertIn("accuracy", decision.reasons[0])

    def test_stale_document_aborts(self) -> None:
        decision = self.policy.evaluate(_metrics(freshness=6.0), Mode.APPLY)
        self.assertIs(decision.outcome, GateOutcome.ABORT)

    def test_propose_mode_never_publishes(self) -> None:
        decision = self.policy.evaluate(_metrics(), Mode.PROPOSE)
        self.assertIs(decision.outcome, GateOutcome.REVIEW)

    def test_thresholds_are_per_metric(self) -> None:
        # Concisión 7.4 falla su propio umbral (7.5) aunque el resto sea excelente.
        decision = self.policy.evaluate(_metrics(conciseness=7.4), Mode.APPLY)
        self.assertIs(decision.outcome, GateOutcome.REVIEW)
        self.assertTrue(any("conciseness" in r for r in decision.reasons))


class BudgetTests(unittest.TestCase):
    def test_spending_within_budget_is_silent(self) -> None:
        budget = Budget(max_cost_usd=1.0)
        budget.spend(usd=0.4, seconds=10, pages=2, calls=3)
        self.assertAlmostEqual(budget.remaining_usd, 0.6)

    def test_cost_overrun_raises(self) -> None:
        budget = Budget(max_cost_usd=0.5)
        with self.assertRaises(BudgetExhausted):
            budget.spend(usd=0.6)

    def test_page_overrun_raises(self) -> None:
        budget = Budget(max_pages=1)
        with self.assertRaises(BudgetExhausted):
            budget.spend(pages=2)

    def test_exceeded_lists_every_violation(self) -> None:
        budget = Budget(max_cost_usd=0.1, max_pages=1)
        budget.spent_usd, budget.pages_written = 0.2, 5
        self.assertEqual(len(budget.exceeded()), 2)


if __name__ == "__main__":
    unittest.main()
