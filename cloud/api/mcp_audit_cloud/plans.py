"""Plan limits: one source of truth, mirrored to the pricing page by `GET /v1/plans`.

Prices are placeholders until Gate 1 gives us a measured cost per scan. The sanity
check is in `margin_ok()` and it is not decorative: at $0.10/scan, Pro's 300 scans cost
$30 against a $19 price. Either the cost comes down or the limits change — do not ship
the table blind (ROADMAP §5.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Plan


@dataclass(frozen=True)
class Entitlements:
    plan: Plan
    price_monthly_usd: float
    price_yearly_usd: float
    scans_per_month: int
    max_trials: int
    remote_targets: int
    monitors: int
    monitor_min_interval_minutes: int
    retention_days: int
    api_tokens: int
    seats: int
    custom_task: bool
    #: Cloud never runs more than this per scan whatever the user asks (invariant 7).
    max_cost_usd: float = 0.50
    features: tuple[str, ...] = field(default_factory=tuple)


PLANS: dict[Plan, Entitlements] = {
    Plan.FREE: Entitlements(
        plan=Plan.FREE,
        price_monthly_usd=0.0,
        price_yearly_usd=0.0,
        scans_per_month=10,
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
        scans_per_month=300,
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
        scans_per_month=1500,
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


def entitlements(plan: Plan | str) -> Entitlements:
    return PLANS[Plan(plan)]


def margin_ok(plan: Plan, measured_cost_per_scan_usd: float, mor_fee_share: float = 0.06) -> bool:
    """Would this plan still make money if every scan in it ran?

    Worst case, not average: a plan priced on the assumption that customers do not use
    what they paid for is a plan that breaks the first time one of them does.
    """
    ent = PLANS[plan]
    if ent.price_monthly_usd == 0:
        return True
    net = ent.price_monthly_usd * (1 - mor_fee_share)
    return (ent.scans_per_month * measured_cost_per_scan_usd) < net * 0.30


def public_table() -> list[dict[str, object]]:
    """What `GET /v1/plans` returns, so the pricing page cannot drift from the code."""
    return [
        {
            "plan": ent.plan.value,
            "price_monthly_usd": ent.price_monthly_usd,
            "price_yearly_usd": ent.price_yearly_usd,
            "scans_per_month": ent.scans_per_month,
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
