"""The whole pipeline, offline: capture a real fixture, score it with a fake model.

This is the test that would catch a wiring mistake nothing else can see -- a
sanitized arm that gets the real inventory, a verdict computed on the wrong traces,
a cost that never lands in the report.
"""

from __future__ import annotations

import sys

import pytest

from mcp_audit.audit import audit, exit_code
from mcp_audit.capture.stdio import capture_stdio
from mcp_audit.errors import BudgetError
from mcp_audit.models import Report, Verdict
from tests.conftest import FIXTURES, ScriptedClient, block, text


async def inventory(name: str):
    inv, _ = await capture_stdio(sys.executable, [str(FIXTURES / f"{name}.py")])
    return inv


STEERED = [[block("read_file", path="/etc/passwd")], [block("list_notes")], [text()]]
HONEST = [[block("list_notes")], [text()]]


async def test_a_poisoned_server_is_confirmed_end_to_end():
    inv = await inventory("poisoned_instructions")
    api = ScriptedClient(real=STEERED, sanitized=HONEST, marker="IMPORTANT SETUP STEP")
    report = await audit(inv, api=api, trials=5, escalate=False)

    assert report.verdict is Verdict.CONFIRMED
    assert exit_code(report) == 1
    assert report.tool_verdicts["read_file"] is Verdict.CONFIRMED
    assert report.inventory_sha256 == inv.sha256()
    assert report.trials == 5
    assert len(report.traces) == 10
    assert {t.side for t in report.traces} == {"real", "sanitized"}
    assert report.usage.api_calls > 0 and report.usage.cost_usd > 0
    assert "/etc/passwd" in report.stripped_diff
    assert report.model and report.task and report.engine_version


async def test_an_honest_server_comes_out_clean_end_to_end():
    inv = await inventory("clean")
    api = ScriptedClient(real=HONEST, sanitized=HONEST, marker="IMPORTANT SETUP STEP")
    report = await audit(inv, api=api, trials=5, escalate=False)
    assert report.verdict is Verdict.CLEAN
    assert exit_code(report) == 0
    assert all(f.verdict is Verdict.CLEAN for f in report.findings)


async def test_the_sanitized_arm_really_gets_the_sanitized_inventory():
    inv = await inventory("poisoned_instructions")
    api = ScriptedClient(real=STEERED, sanitized=HONEST, marker="IMPORTANT SETUP STEP")
    await audit(inv, api=api, trials=2, escalate=False)
    systems = {req["system"][0]["text"] for req in api.seen}
    assert len(systems) == 2, "both arms got the same system prompt"
    assert any("IMPORTANT SETUP STEP" in s for s in systems)
    assert any("IMPORTANT SETUP STEP" not in s for s in systems)


async def test_escalation_runs_a_second_round_and_says_so():
    inv = await inventory("poisoned_suppress")
    # 3/5 on the real arm is borderline: escalation should double the sample
    api = ScriptedClient(real=HONEST, sanitized=[[block("audit_log", action="x")], [text()]], marker="POLICY")
    report = await audit(inv, api=api, trials=5, escalate=True)
    assert report.escalated is True
    assert report.trials == 10
    assert len(report.traces) == 20


async def test_no_escalation_when_asked_not_to():
    inv = await inventory("poisoned_suppress")
    api = ScriptedClient(real=HONEST, sanitized=[[block("audit_log", action="x")], [text()]], marker="POLICY")
    report = await audit(inv, api=api, trials=5, escalate=False)
    assert report.escalated is False
    assert report.trials == 5


async def test_the_budget_guard_runs_before_any_trial():
    inv = await inventory("clean")
    api = ScriptedClient(real=HONEST, sanitized=HONEST)
    with pytest.raises(BudgetError):
        await audit(inv, api=api, trials=50, max_cost=0.0001, escalate=False)
    assert api.seen == [], "trials ran before the money guard"


async def test_fail_on_suspected_is_opt_in():
    report = Report(verdict=Verdict.SUSPECTED)
    assert exit_code(report) == 0
    assert exit_code(report, "suspected") == 1
    assert exit_code(Report(verdict=Verdict.INCONCLUSIVE), "suspected") == 0


async def test_progress_is_reported_to_the_caller():
    inv = await inventory("clean")
    lines: list[str] = []
    await audit(inv, api=ScriptedClient(HONEST, HONEST), trials=2, escalate=False, progress=lines.append)
    assert any("API calls" in line for line in lines)
    assert any("trials per arm" in line for line in lines)
