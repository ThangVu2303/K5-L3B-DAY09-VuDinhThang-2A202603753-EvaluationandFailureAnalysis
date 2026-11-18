"""Regression test for docs/trace_case.md: seeded_regression C-014@11 (FM-05 pre_deducted).

First wrong step: event `proposal` = 120000 after `refund_history` showed a 30000 past refund.
The host deducts the past refund again, so the ledger holds 90000 while the reply says 120000.
The same claim@seed on `fixed` must pass both graders, so the test pins the bug, not the claim.
"""
import pytest

pytestmark = pytest.mark.student


def _ctx(case):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=case["label"],
                            output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})


def _grade(shape):
    from lab9 import graders, trace_case

    ctx = _ctx(trace_case.investigate(shape, "C-014", 11))
    return {name: graders.GRADERS[name]().evaluate(ctx).value
            for name in ("proposal_correct", "reply_matches_ledger", "refund_amount_correct")}


def test_lab9_regression_c014_pre_deducted_is_caught():
    got = _grade("seeded_regression")
    assert got == {"proposal_correct": False, "reply_matches_ledger": False, "refund_amount_correct": False}


def test_lab9_regression_c014_fixed_passes():
    assert all(_grade("fixed").values())
