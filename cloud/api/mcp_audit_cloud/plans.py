"""Plan limits: one source of truth, mirrored to the pricing page by `GET /v1/plans`.

**The binding limit is money, not scan count.** A scan is not a fixed-cost unit: a
26-tool server at 10 trials per arm costs many times a 3-tool server at 5. Counting scans
therefore bounds nothing, and a plan priced on a scan count is a plan that loses money the
first time somebody points it at a big server.

So each plan includes a number of **dollars of model time** (`included_model_usd`), that
number is enforced per period (`services/quota.py`), and the advertised scan count is
*derived* from it. The two cannot contradict each other, because only one of them is real.

What this buys: the margin is guaranteed by arithmetic rather than by hoping the cost
estimate holds. Gate 1's measured cost per scan then decides how *many* scans a budget
buys — a marketing question — instead of deciding whether the business is solvent.

The budgets below follow the rule ROADMAP §5.1 already states: model spend stays under
30% of the plan price after merchant-of-record fees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .models import Plan

#: What one scan costs us, in USD. **Provisional and deliberately pessimistic** until
#: Gate 1 measures it (`uv run pytest -q -m gate`, then `bench/fixtures.md`).
#:
#: Reasoning for the default: 2 arms x 5 trials x ~3 turns = ~30 calls; ~1.5k input and
#: ~200 output tokens per call on claude-haiku-4-5 ($1/$5 per MTok), with prompt caching
#: cutting most of the repeated input. That lands near $0.03; we assume double.
#:
#: Overestimating is the safe direction: it advertises fewer scans than the budget buys.
#: Underestimating advertises scans the budget cannot pay for, which is the failure this
#: whole module exists to prevent.
ESTIMATED_COST_PER_SCAN_USD = 0.06

#: Merchant-of-record cut (D9). Dodo's take, so revenue we never see.
MOR_FEE_SHARE = 0.06

#: Share of net revenue we are willing to spend on model time. ROADMAP §5.1.
MODEL_SPEND_SHARE = 0.30


@dataclass(frozen=True)
class Entitlements:
    plan: Plan
    price_monthly_usd: float
    price_yearly_usd: float
    #: **The real limit.** Dollars of model time included per period, enforced by
    #: `quota.reserve()`. Everything else here is a comfort limit.
    included_model_usd: float
    max_trials: int
    remote_targets: int
    monitors: int
    monitor_min_interval_minutes: int
    retention_days: int
    api_tokens: int
    seats: int
    custom_task: bool
    #: Cloud never runs more than this on one scan, whatever the user asks (invariant 7).
    #: Also clamped to what is left of the period budget, so the last scan of a period
    #: cannot overshoot it.
    max_cost_usd: float = 0.50
    features: tuple[str, ...] = field(default_factory=tuple)

    @property
    def scans_per_month(self) -> int:
        """Derived, never hand-set: what the budget buys at our current cost estimate.

        A property rather than a stored field so it is impossible to ship a table where
        the advertised count and the budget disagree.
        """
        return max(1, math.floor(self.included_model_usd / ESTIMATED_COST_PER_SCAN_USD))

    @property
    def budget_micros(self) -> int:
        return int(self.included_model_usd * 1_000_000)

    @property
    def net_revenue_usd(self) -> float:
        return self.price_monthly_usd * (1 - MOR_FEE_SHARE)

    @property
    def worst_case_margin_usd(self) -> float:
        """What we keep if a customer spends every dollar of model time included.

        Not "on average". A plan whose margin depends on customers not using what they
        paid for is a plan that breaks the first time one of them does.
        """
        return self.net_revenue_usd - self.included_model_usd


PLANS: dict[Plan, Entitlements] = {
    Plan.FREE: Entitlements(
        plan=Plan.FREE,
        price_monthly_usd=0.0,
        price_yearly_usd=0.0,
        # Free is a marketing cost, so it is a *chosen* number rather than a consequence.
        # $0.30 per org per month, on top of the global daily breaker and a cap on how
        # many free orgs one person can create. Enough to scan a few real servers and
        # decide whether the verdict is worth paying for.
        included_model_usd=0.30,
        max_trials=5,
        remote_targets=1,
        monitors=0,
        monitor_min_interval_minutes=0,
        retention_days=7,
        api_tokens=1,
        seats=1,
        # A custom task is the LLM-proxy abuse channel (docs/SECURITY.md §6), so the
        # free tier gets the default task only.
        custom_task=False,
        max_cost_usd=0.10,
        features=("share_links", "sarif"),
    ),
    Plan.PRO: Entitlements(
        plan=Plan.PRO,
        price_monthly_usd=19.0,
        price_yearly_usd=190.0,
        # 30% of $19 net of the MoR fee is $5.36; $5.00 leaves the rounding on our side.
        included_model_usd=5.00,
        max_trials=10,
        remote_targets=20,
        monitors=10,
        monitor_min_interval_minutes=60 * 24,
        retention_days=365,
        api_tokens=10,
        seats=1,
        custom_task=True,
        max_cost_usd=0.50,
        features=("share_links", "sarif", "monitors", "history", "webhooks"),
    ),
    Plan.TEAM: Entitlements(
        plan=Plan.TEAM,
        price_monthly_usd=79.0,
        price_yearly_usd=790.0,
        # 30% of $79 net is $22.28.
        included_model_usd=22.00,
        max_trials=20,
        remote_targets=100,
        monitors=100,
        monitor_min_interval_minutes=60,
        retention_days=730,
        api_tokens=50,
        seats=10,
        custom_task=True,
        max_cost_usd=1.00,
        features=("share_links", "sarif", "monitors", "history", "webhooks", "members", "sso_later"),
    ),
}

EXTRA_SEAT_USD = 8.0

#: How many free organisations one account may own. Without this, "free per org" is
#: "free per org somebody bothers to create", which is not a limit (SECURITY.md §6).
MAX_FREE_ORGS_PER_USER = 2


def entitlements(plan: Plan | str) -> Entitlements:
    return PLANS[Plan(plan)]


def margin_ok(plan: Plan) -> bool:
    """Would this plan still make money if a customer spent every included dollar?

    Takes no cost-per-scan argument any more, and that is the point: spend is capped in
    dollars, so the answer does not depend on an estimate being right.
    """
    ent = PLANS[plan]
    if ent.price_monthly_usd == 0:
        return True  # free has no margin to protect; it has a budget instead
    return ent.included_model_usd <= ent.net_revenue_usd * MODEL_SPEND_SHARE


def free_tier_worst_case_usd(signups: int) -> float:
    """What `signups` free accounts cost us at most, per month.

    The number to look at before advertising anywhere: it is bounded, which is the whole
    point, but it is not zero.
    """
    return signups * PLANS[Plan.FREE].included_model_usd * MAX_FREE_ORGS_PER_USER


def public_table() -> list[dict[str, object]]:
    """What `GET /v1/plans` returns, so the pricing page cannot drift from the code."""
    return [
        {
            "plan": ent.plan.value,
            "price_monthly_usd": ent.price_monthly_usd,
            "price_yearly_usd": ent.price_yearly_usd,
            "scans_per_month": ent.scans_per_month,
            "included_model_usd": ent.included_model_usd,
            "max_trials": ent.max_trials,
            "remote_targets": ent.remote_targets,
            "monitors": ent.monitors,
            "monitor_min_interval_minutes": ent.monitor_min_interval_minutes,
            "retention_days": ent.retention_days,
            "api_tokens": ent.api_tokens,
            "seats": ent.seats,
            "custom_task": ent.custom_task,
            "features": list(ent.features),
            "extra_seat_usd": EXTRA_SEAT_USD if ent.plan is Plan.TEAM else None,
        }
        for ent in PLANS.values()
    ]
