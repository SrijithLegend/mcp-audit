"""Live tests. Real model, real money. Deselected unless you ask for them:

    uv run pytest -q -m live            # a few cents
    uv run pytest -q -m live --gate     # the Gate 1 matrix, ~$5-10 (ask first)

`--gate` runs each fixture 10 times per ROADMAP Gate 1 and prints the table that
goes in bench/fixtures.md. Nothing here runs in CI.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys

import pytest

from mcp_audit.audit import audit
from mcp_audit.capture.stdio import capture_stdio
from mcp_audit.harness import client
from mcp_audit.models import Verdict
from tests.conftest import FIXTURES

pytestmark = pytest.mark.live

POISONED = (
    "poisoned_instructions",
    "poisoned_param",
    "poisoned_tool_desc",
    "poisoned_nested",
    "poisoned_suppress",
)
CONTROLS = ("clean", "benign_verbose")
GATE_RUNS = 10


def requires_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("live tests need ANTHROPIC_API_KEY")


async def scan_fixture(name: str, trials: int = 5, max_cost: float = 0.50):
    inventory, _ = await capture_stdio(sys.executable, [str(FIXTURES / f"{name}.py")])
    return await audit(
        inventory,
        api=client(),
        trials=trials,
        max_cost=max_cost,
        assume_yes=True,
        interactive=False,
    )


@pytest.mark.parametrize("name", POISONED)
def test_poisoned_fixture_is_caught(name):
    requires_key()
    report = asyncio.run(scan_fixture(name))
    assert report.verdict in (Verdict.CONFIRMED, Verdict.SUSPECTED), report.model_dump_json(indent=2)


@pytest.mark.parametrize("name", CONTROLS)
def test_control_fixture_is_not_confirmed(name):
    """The number the whole pitch rests on: no false positives on honest servers."""
    requires_key()
    report = asyncio.run(scan_fixture(name))
    assert report.verdict is not Verdict.CONFIRMED, report.model_dump_json(indent=2)


@pytest.mark.gate
@pytest.mark.parametrize("name", POISONED + CONTROLS)
def test_gate_1_matrix(name, record_property):
    """ROADMAP Gate 1: 10 runs per fixture; poisoned >= 9/10 CONFIRMED, controls 0/10."""
    requires_key()
    verdicts, costs = [], []
    for _ in range(GATE_RUNS):
        report = asyncio.run(scan_fixture(name))
        verdicts.append(report.verdict)
        costs.append(report.usage.cost_usd)
    confirmed = sum(v is Verdict.CONFIRMED for v in verdicts)
    median = statistics.median(costs)
    record_property("confirmed", confirmed)
    record_property("median_cost_usd", median)
    print(f"\n{name}: CONFIRMED {confirmed}/{GATE_RUNS}, median ${median:.4f}")
    if name in CONTROLS:
        assert confirmed == 0, f"false positive on {name}: {verdicts}"
    else:
        assert confirmed >= 9, f"{name} only confirmed {confirmed}/{GATE_RUNS}: {verdicts}"
