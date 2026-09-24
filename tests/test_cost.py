"""The money guard. A hard stop, and priced from the real turn-1 payload."""

from __future__ import annotations

import pytest

from mcp_audit.cost import PRICES, Estimate, dollars, estimate, guard, price
from mcp_audit.errors import BudgetError
from mcp_audit.models import Usage
from mcp_audit.sanitizer import sanitize
from tests.conftest import FakeClient


def test_haiku_price_is_the_documented_one():
    assert PRICES["claude-haiku-4-5"] == (1.00, 5.00)


def test_an_unknown_model_is_priced_as_the_most_expensive_one_we_know():
    """Erring the other way would let the guard wave through a $20 scan."""
    assert price("claude-something-new-9") == max(PRICES.values(), key=lambda p: p[1])


def test_cached_reads_are_a_tenth_of_input():
    full = dollars(Usage(input_tokens=1_000_000), "claude-haiku-4-5")
    cached = dollars(Usage(cache_read_tokens=1_000_000), "claude-haiku-4-5")
    assert full == pytest.approx(1.00)
    assert cached == pytest.approx(0.10)
    assert dollars(Usage(output_tokens=1_000_000), "claude-haiku-4-5") == pytest.approx(5.00)


async def test_estimate_counts_the_real_payload_of_both_arms(notes_inventory):
    fake = FakeClient()
    est = await estimate(notes_inventory, sanitize(notes_inventory), "task", trials=5, api=fake)
    # 2 arms x 5 trials x 3 expected turns
    assert est.api_calls == 30
    assert est.input_tokens == 500
    assert len(fake.counted) == 2, "both arms are counted, not just the real one"
    assert "~30 API calls" in est.line()
    assert est.worst_usd > est.expected_usd


async def test_estimate_falls_back_to_a_guess_when_counting_is_unavailable(notes_inventory):
    est = await estimate(notes_inventory, sanitize(notes_inventory), "task", trials=2, api=None)
    assert est.input_tokens > 0


def test_guard_is_a_hard_stop():
    est = Estimate(api_calls=1000, input_tokens=100_000, model="claude-haiku-4-5")
    with pytest.raises(BudgetError, match="exceeds --max-cost"):
        guard(est, max_cost=0.01, assume_yes=False, interactive=True)
    # --yes accepts it; a cheap scan never asks
    guard(est, max_cost=0.01, assume_yes=True, interactive=True)
    guard(Estimate(10, 100, "claude-haiku-4-5"), max_cost=1.0, assume_yes=False, interactive=True)


def test_ci_is_told_to_raise_the_limit_not_to_answer_a_prompt():
    est = Estimate(api_calls=1000, input_tokens=100_000, model="claude-haiku-4-5")
    with pytest.raises(BudgetError, match="Raise --max-cost in CI"):
        guard(est, max_cost=0.01, assume_yes=False, interactive=False)
