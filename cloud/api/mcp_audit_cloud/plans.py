"""Plan limits: one source of truth, mirrored to the pricing page by `GET /v1/plans`.

**We do not pay for inference, so none of these numbers protect a margin.**

Every scan runs where the key already is — the user's machine or their CI, on their own
Anthropic key — and the Cloud stores, compares and monitors the results. `tests/` greps
this whole directory to prove no code path here can call a model (D12'). So the limits
below are *product and anti-abuse* limits: they bound our database, queue and bandwidth,
and they mark the line between the free tier and the paid one. They are not a hedge against
an Anthropic bill, because there isn't one.

What that changes about setting them: the only question is what the infrastructure can take
and what makes the free tier a fair trial, not what we can afford. A number here being
wrong costs us disk, not money.

Team is still defined because subscriptions and rows may reference it, but it is not sold
(`listed=False`), so it never reaches the pricing page.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Plan


@dataclass(frozen=True)
class Entitlements:
    plan: Plan
    price_monthly_usd: float
    price_yearly_usd: float
    #: Reports we will accept and keep per period. An anti-abuse and storage limit: each
    #: one is a few hundred KB of JSONB we hold for the retention window.
    reports_per_month: int
    #: How many distinct servers (targets) an org may track.
    targets: int
    monitors: int
    monitor_min_interval_minutes: int
    retention_days: int
    api_tokens: int
    seats: int
    #: Trials per arm we accept in an uploaded report. Not a cost limit -- the user paid
    #: for those tokens -- but a deep audit is a paid feature, so the free tier gets the
    #: shallow one.
    max_trials: int
    #: Whether an uploaded report may carry a custom task. Free gets the default task only,
    #: which keeps free reports comparable with each other.
    custom_task: bool
    #: Sold on the pricing page. Team is kept in code for existing rows, not advertised.
    listed: bool = True
    features: tuple[str, ...] = field(default_factory=tuple)

    @property
    def net_revenue_usd(self) -> float:
        """After the merchant-of-record cut (D9). Kept for the pricing page, not for a
        margin calculation -- there is no variable cost to subtract any more."""
        return self.price_monthly_usd * (1 - MOR_FEE_SHARE)


#: Merchant-of-record cut (D9). Dodo's take, so revenue we never see.
MOR_FEE_SHARE = 0.06

#: How many free organisations one account may own. Free is a trial, not a supply.
MAX_FREE_ORGS_PER_USER = 2

#: Upper bound on one uploaded report, before pydantic even looks at it. A report with
#: 500 tools x 20 trials of traces is the shape that fills a database.
MAX_REPORT_BYTES = 4 * 1024 * 1024


PLANS: dict[Plan, Entitlements] = {
    Plan.FREE: Entitlements(
        plan=Plan.FREE,
        price_monthly_usd=0.0,
        price_yearly_usd=0.0,
        reports_per_month=5,
        targets=3,
        monitors=0,
        monitor_min_interval_minutes=0,
        retention_days=7,
        api_tokens=1,
        seats=1,
        max_trials=5,
        custom_task=False,
        features=("share_links", "sarif"),
    ),
    Plan.PRO: Entitlements(
        plan=Plan.PRO,
        price_monthly_usd=19.0,
        price_yearly_usd=190.0,
        reports_per_month=500,
        # "Unlimited" on a pricing page is a promise about someone else's disk. 100 is more
        # servers than anyone has and still a number we can reason about.
        targets=100,
        monitors=25,
        monitor_min_interval_minutes=60,
        retention_days=365,
        api_tokens=10,
        seats=1,
        max_trials=20,
        custom_task=True,
        features=("share_links", "sarif", "monitors", "history", "webhooks", "priority"),
    ),
    Plan.TEAM: Entitlements(
        plan=Plan.TEAM,
        price_monthly_usd=79.0,
        price_yearly_usd=790.0,
        reports_per_month=2000,
        targets=250,
        monitors=100,
        monitor_min_interval_minutes=60,
        retention_days=730,
        api_tokens=50,
        seats=10,
        max_trials=20,
        custom_task=True,
        # Built, and deliberately not sold yet: seats are where a security tool usually
        # gets bought, so this comes back the first time somebody asks. One flag.
        listed=False,
        features=("share_links", "sarif", "monitors", "history", "webhooks", "members", "priority"),
    ),
}

EXTRA_SEAT_USD = 8.0


def entitlements(plan: Plan | str) -> Entitlements:
    return PLANS[Plan(plan)]


def listed_plans() -> list[Entitlements]:
    return [ent for ent in PLANS.values() if ent.listed]


def public_table() -> list[dict[str, object]]:
    """What `GET /v1/plans` returns, so the pricing page cannot drift from the code."""
    return [
        {
            "plan": ent.plan.value,
            "price_monthly_usd": ent.price_monthly_usd,
            "price_yearly_usd": ent.price_yearly_usd,
            "reports_per_month": ent.reports_per_month,
            "targets": ent.targets,
            "monitors": ent.monitors,
            "monitor_min_interval_minutes": ent.monitor_min_interval_minutes,
            "retention_days": ent.retention_days,
            "api_tokens": ent.api_tokens,
            "seats": ent.seats,
            "max_trials": ent.max_trials,
            "custom_task": ent.custom_task,
            "features": list(ent.features),
            "extra_seat_usd": EXTRA_SEAT_USD if ent.plan is Plan.TEAM else None,
        }
        for ent in listed_plans()
    ]
