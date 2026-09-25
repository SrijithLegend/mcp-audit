"""What hosted scanning can cost *us*, at worst.

The question these tests answer: can a customer, or a crowd of free signups, or a bug in
our own cost estimate, make the hosted service cost more than it earns? Every answer here
has to be no, and has to be no by arithmetic rather than by hoping the estimate holds.

The one number that is still a guess is `ESTIMATED_COST_PER_SCAN_USD`, and it only decides
how many scans a budget buys — not whether the budget is respected.
"""

from __future__ import annotations

import pytest

from mcp_audit_cloud.errors import Problem
from mcp_audit_cloud.models import Org, Plan, Usage
from mcp_audit_cloud.plans import (
    ESTIMATED_COST_PER_SCAN_USD,
    MAX_FREE_ORGS_PER_USER,
    MODEL_SPEND_SHARE,
    PLANS,
    entitlements,
    free_tier_worst_case_usd,
    margin_ok,
)
from mcp_audit_cloud.services import quota

# --- the table itself cannot be a losing one -------------------------------------


@pytest.mark.parametrize("plan", list(Plan))
def test_every_paid_plan_keeps_most_of_its_revenue_at_full_use(plan):
    """Worst case, not average: a plan whose margin needs customers to under-use it is a
    plan that breaks the first time one of them doesn't."""
    ent = entitlements(plan)
    assert margin_ok(plan), f"{plan} spends more than {MODEL_SPEND_SHARE:.0%} of net revenue"
    if ent.price_monthly_usd > 0:
        assert ent.worst_case_margin_usd > 0, f"{plan} loses money when fully used"


def test_the_advertised_scan_count_is_derived_from_the_budget():
    """Not hand-set. A table where the count and the budget disagree is a table that
    promises scans the budget cannot pay for."""
    for ent in PLANS.values():
        assert ent.scans_per_month == max(1, int(ent.included_model_usd // ESTIMATED_COST_PER_SCAN_USD))
        # The promise is payable at our estimate, with the floor rounding in our favour.
        assert ent.scans_per_month * ESTIMATED_COST_PER_SCAN_USD <= ent.included_model_usd + 1e-9


def test_a_single_scan_can_never_exceed_the_period_budget():
    for ent in PLANS.values():
        assert ent.max_cost_usd <= ent.included_model_usd, (
            f"{ent.plan}: one scan may cost ${ent.max_cost_usd} out of a ${ent.included_model_usd} budget"
        )


def test_free_costs_a_bounded_and_knowable_amount():
    """Free is a marketing cost. It has to be a number you chose, not a consequence."""
    free = entitlements(Plan.FREE)
    assert free.included_model_usd <= 0.50
    # 1,000 signups, each with the maximum number of free orgs.
    assert free_tier_worst_case_usd(1000) <= 1000.0
    assert free_tier_worst_case_usd(1) == pytest.approx(free.included_model_usd * MAX_FREE_ORGS_PER_USER)


def test_a_worse_cost_per_scan_shrinks_the_offer_instead_of_the_margin():
    """If Gate 1 says scans cost double, customers get fewer of them -- we do not get a
    bill. That is the property the whole design is for."""
    import mcp_audit_cloud.plans as plans

    before = entitlements(Plan.PRO).scans_per_month
    original = plans.ESTIMATED_COST_PER_SCAN_USD
    try:
        plans.ESTIMATED_COST_PER_SCAN_USD = original * 2
        after = entitlements(Plan.PRO).scans_per_month
    finally:
        plans.ESTIMATED_COST_PER_SCAN_USD = original
    assert after < before
    assert margin_ok(Plan.PRO), "the budget, and so the margin, is unchanged"


# --- and the running system honours it --------------------------------------------


async def org_on(db, plan: Plan, spent_usd: float = 0.0) -> Org:
    org = Org(name=str(plan), slug=f"s-{plan}-{spent_usd}", plan=plan, personal=False)
    db.add(org)
    await db.flush()
    if spent_usd:
        db.add(
            Usage(
                org_id=org.id,
                period_start=quota.period_start(),
                scans_used=0,
                cost_micros=int(spent_usd * 1_000_000),
            )
        )
        await db.flush()
    return org


async def test_a_scan_is_refused_once_the_model_budget_is_gone(db):
    """The leak this closes: cost_micros used to be recorded and never read."""
    free = entitlements(Plan.FREE)
    org = await org_on(db, Plan.FREE, spent_usd=free.included_model_usd)
    with pytest.raises(Problem) as exc:
        await quota.reserve(db, org.id, Plan.FREE)
    assert exc.value.code == "budget_exceeded"
    assert exc.value.status == 402
    # And it says something a customer can act on rather than just "no".
    assert "CLI is unaffected" in exc.value.detail


async def test_a_scan_is_refused_when_only_part_of_one_scan_is_affordable(db):
    """Starting a scan we cannot pay to finish wastes the model time it does use."""
    free = entitlements(Plan.FREE)
    org = await org_on(db, Plan.FREE, spent_usd=free.included_model_usd - free.max_cost_usd / 2)
    with pytest.raises(Problem) as exc:
        await quota.reserve(db, org.id, Plan.FREE)
    assert exc.value.code == "budget_exceeded"


async def test_spend_is_bounded_by_the_budget_even_when_every_scan_costs_the_maximum(db):
    """The headline: run scans until refused, and the total cannot pass the budget by more
    than the one scan in flight."""
    plan = Plan.PRO
    ent = entitlements(plan)
    org = await org_on(db, plan)

    spent = 0.0
    for _ in range(ent.scans_per_month + 50):
        try:
            await quota.reserve(db, org.id, plan)
        except Problem as exc:
            assert exc.code in ("budget_exceeded", "quota_exceeded")
            break
        # The engine's own guard caps one scan here; assume the worst every time.
        ceiling = await quota.allowed_scan_cost(db, org.id, plan)
        await quota.record_cost(db, org.id, int(ceiling * 1_000_000))
        spent += ceiling
    else:  # pragma: no cover - would mean nothing ever refused
        pytest.fail("the budget never ran out")

    assert spent <= ent.included_model_usd + 1e-6
    assert spent <= ent.net_revenue_usd * MODEL_SPEND_SHARE + 1e-6


async def test_the_per_scan_ceiling_shrinks_as_the_budget_runs_down(db):
    """So the last scan of a period cannot overshoot the budget."""
    ent = entitlements(Plan.PRO)
    org = await org_on(db, Plan.PRO, spent_usd=ent.included_model_usd - 0.05)
    ceiling = await quota.allowed_scan_cost(db, org.id, Plan.PRO)
    assert ceiling == pytest.approx(0.05)
    assert ceiling < ent.max_cost_usd


async def test_a_spent_budget_leaves_no_headroom_at_all(db):
    ent = entitlements(Plan.TEAM)
    org = await org_on(db, Plan.TEAM, spent_usd=ent.included_model_usd + 5)
    assert await quota.allowed_scan_cost(db, org.id, Plan.TEAM) == 0.0
    assert await quota.has_budget(db, org.id, Plan.TEAM) is False


async def test_the_scan_count_still_bounds_a_run_of_nearly_free_scans(db):
    """Budget is the real limit, but a pathological run of cheap scans is still work we
    are doing for someone, so the derived count is enforced too."""
    plan = Plan.FREE
    org = await org_on(db, plan)
    accepted = 0
    for _ in range(entitlements(plan).scans_per_month + 5):
        try:
            await quota.reserve(db, org.id, plan)
        except Problem as exc:
            assert exc.code == "quota_exceeded"
            break
        accepted += 1
        await quota.record_cost(db, org.id, 1)  # a micro-dollar: effectively free
    assert accepted == entitlements(plan).scans_per_month


async def test_our_outage_refunds_the_money_as_well_as_the_count(db):
    """A refund that gives back the scan but keeps the reserved cost would quietly shrink
    the customer's budget every time we had a bad day."""
    org = await org_on(db, Plan.PRO)
    await quota.reserve(db, org.id, Plan.PRO, cost_micros=40_000)
    before = await quota.current(db, org.id)
    assert before.scans_used == 1 and before.cost_micros == 40_000

    await quota.refund(db, org.id, cost_micros=40_000)
    after = await quota.current(db, org.id)
    assert after.scans_used == 0
    assert after.cost_micros == 0


async def test_a_refund_never_becomes_a_credit(db):
    org = await org_on(db, Plan.PRO)
    await quota.refund(db, org.id, cost_micros=500_000)
    assert (await quota.current(db, org.id)).cost_micros == 0


async def test_an_overspending_scan_eats_into_the_same_budget(db):
    """A scan that comes in over its estimate must not be forgotten -- otherwise the
    estimate being wrong is our problem instead of the customer's allowance."""
    plan = Plan.FREE
    org = await org_on(db, plan)
    await quota.reserve(db, org.id, plan)
    await quota.record_cost(db, org.id, int(entitlements(plan).included_model_usd * 1_000_000))
    with pytest.raises(Problem) as exc:
        await quota.reserve(db, org.id, plan)
    assert exc.value.code == "budget_exceeded"
