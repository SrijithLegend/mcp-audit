"""What hosted scanning costs us: **nothing**, and structurally rather than by policy.

Scans run in the user's CLI or CI on the user's own Anthropic key. This service ingests the
finished report. So there is no budget to enforce and no margin to protect — the question
these tests answer is narrower and much stronger: *can this codebase call a model at all?*

The remaining limits bound storage, bandwidth and abuse. They are tested here too, because a
limit nobody checks is decoration.
"""

from __future__ import annotations

import pathlib

import pytest

from mcp_audit_cloud.config import Settings
from mcp_audit_cloud.errors import Problem
from mcp_audit_cloud.models import Org, Plan
from mcp_audit_cloud.plans import MAX_FREE_ORGS_PER_USER, PLANS, entitlements, listed_plans
from mcp_audit_cloud.services import quota

PACKAGE = pathlib.Path(__file__).resolve().parents[1] / "mcp_audit_cloud"

#: Anything that would mean we are paying for inference. The engine is a dependency -- we
#: use its models, its report renderers and its capture layer -- but never the half of it
#: that spends money.
INFERENCE = (
    "anthropic",
    "AsyncAnthropic",
    "messages.create",
    "count_tokens",
    "mcp_audit.harness",
    "mcp_audit.audit",
    "mcp_audit.cost",
)


def sources() -> list[pathlib.Path]:
    return [p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts]


def test_the_cloud_cannot_call_a_model():
    """The whole business model, as a grep.

    If this fails, somebody has reintroduced an inference path and our costs are no longer
    zero. Note `mcp_audit.harness` and `mcp_audit.audit` are in the list: importing the
    engine's agent loop is exactly how this would come back.
    """
    offenders = []
    for path in sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            for needle in INFERENCE:
                if needle in code:
                    offenders.append(f"{path.relative_to(PACKAGE)}:{number}: {line.strip()}")
    assert not offenders, "an inference path exists in cloud/api:\n" + "\n".join(offenders)


def test_there_is_no_llm_key_in_the_configuration():
    """Not merely unused -- absent. A setting that exists gets filled in eventually."""
    fields = set(Settings.model_fields)
    assert "anthropic_api_key" not in fields
    assert not [name for name in fields if "anthropic" in name]
    # And nothing left over from when we metered our own spend.
    assert "daily_spend_limit_usd" not in fields
    assert "scan_cost_ceiling_usd" not in fields


def test_the_worker_only_does_things_that_need_no_model():
    from mcp_audit_cloud.worker import WorkerSettings

    names = {fn.__name__ for fn in WorkerSettings.functions}
    # Capture-and-compare, and retention. No run_scan.
    assert names == {"check_monitor", "sweep_monitors", "expire_data"}
    assert "run_scan" not in names


def test_monitoring_detects_changes_without_inference():
    """The half of the rug-pull feature that needs no model is the half we run: capture
    tools/list, hash it, compare. That is why monitoring can be a hosted feature at all."""
    from mcp_audit_cloud.services import monitors

    source = pathlib.Path(monitors.__file__).read_text(encoding="utf-8")
    assert "Scan(" not in source, "monitors must not create scans; scanning needs the user's key"
    assert "capture_http" in source
    assert "sha256" in source


# --- the limits that remain are about storage and abuse, not money ----------------


def test_plans_have_ascending_report_allowances():
    free, pro = entitlements(Plan.FREE), entitlements(Plan.PRO)
    assert free.reports_per_month < pro.reports_per_month
    assert free.targets < pro.targets
    assert free.retention_days < pro.retention_days
    # Free is a trial: shallow audits, default task, no monitoring.
    assert free.monitors == 0
    assert free.custom_task is False
    assert pro.custom_task is True


def test_only_two_plans_are_sold():
    listed = [ent.plan for ent in listed_plans()]
    assert listed == [Plan.FREE, Plan.PRO]
    # Team is still defined, so existing rows and subscriptions resolve.
    assert PLANS[Plan.TEAM].listed is False
    assert entitlements(Plan.TEAM).seats == 10


def test_nothing_in_the_plan_table_mentions_a_model_budget():
    """The fields that existed to protect a margin are gone, not defaulted to zero."""
    fields = set(entitlements(Plan.PRO).__dataclass_fields__)
    assert "included_model_usd" not in fields
    assert "max_cost_usd" not in fields


def test_free_is_bounded_in_storage_terms():
    free = entitlements(Plan.FREE)
    # Worst case per free account: reports x orgs, held for the retention window.
    worst_reports = free.reports_per_month * MAX_FREE_ORGS_PER_USER
    assert worst_reports <= 20, "a free account should not be able to fill a table"


async def org_on(db, plan: Plan) -> Org:
    org = Org(name=str(plan), slug=f"s-{plan}", plan=plan, personal=False)
    db.add(org)
    await db.flush()
    return org


async def test_uploads_are_refused_once_the_period_allowance_is_used(db):
    plan = Plan.FREE
    limit = entitlements(plan).reports_per_month
    org = await org_on(db, plan)

    for _ in range(limit):
        await quota.reserve(db, org.id, plan)
    with pytest.raises(Problem) as exc:
        await quota.reserve(db, org.id, plan)

    assert exc.value.code == "limit_reached"
    assert exc.value.status == 402
    # And it says the thing that matters: scanning itself is not limited by us.
    assert "free and unlimited" in exc.value.detail


async def test_the_customers_own_spend_is_recorded_but_never_gates_anything(db):
    """It is their bill. We show it back to them, and Gate 1 will be glad of the data."""
    org = await org_on(db, Plan.FREE)
    await quota.record_customer_cost(db, org.id, 9_999_999)  # $10 of their money
    usage = await quota.current(db, org.id)
    assert usage.cost_micros == 9_999_999
    # Still allowed to upload: their spend is not our limit.
    await quota.reserve(db, org.id, Plan.FREE)


async def test_a_negative_cost_cannot_be_used_to_rewrite_history(db):
    """The number comes out of an uploaded report, so it is attacker-controlled."""
    org = await org_on(db, Plan.FREE)
    await quota.record_customer_cost(db, org.id, 1_000)
    await quota.record_customer_cost(db, org.id, -500_000)
    assert (await quota.current(db, org.id)).cost_micros == 1_000


async def test_releasing_a_reservation_gives_the_upload_slot_back(db):
    """Only for a failure on our side: the report never got stored."""
    org = await org_on(db, Plan.FREE)
    await quota.reserve(db, org.id, Plan.FREE)
    assert (await quota.current(db, org.id)).scans_used == 1
    await quota.release(db, org.id)
    assert (await quota.current(db, org.id)).scans_used == 0
