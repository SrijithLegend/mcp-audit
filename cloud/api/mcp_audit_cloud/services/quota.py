"""Quota reservation and the spend breakers (invariant 7).

Three things are bounded here, in order of how much they matter to whether this business
survives:

1. **Model spend per org per period.** The real limit (`plans.included_model_usd`). A scan
   is not a fixed-cost unit, so counting scans bounds nothing; counting dollars does.
2. **Scan count per org per period.** Derived from the budget. Kept as a separate check
   because it is the number customers understand, and because it stops a pathological run
   of near-free scans from being unlimited.
3. **Global daily spend**, across every org, as the last line.

The race that matters for all of it: 50 scan submissions arriving at once against a quota
of 10 must accept exactly 10. Checking-then-incrementing in two statements accepts about
50. So the usage row is locked with `SELECT ... FOR UPDATE` and both counters are
incremented inside the same transaction as the check, *before* the job is enqueued.

Reservations are refunded when the failure is ours (an Anthropic outage), not theirs
(a malformed inventory). Charging a customer for our downtime is how you lose them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import insert_ignore
from ..errors import Problem, quota_exceeded
from ..models import Plan, Usage
from ..plans import entitlements

SPEND_KEY = "breaker:spend:"

#: Refuse a scan unless a whole scan's worth of budget is left. Starting one we cannot pay
#: to finish wastes the model time it does use before the engine's own guard stops it.
MIN_BUDGET_HEADROOM = 1.0


def period_start(now: datetime | None = None) -> datetime:
    """Calendar month. Simple, predictable, and what the pricing page says."""
    at = now or datetime.now(UTC)
    return at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def budget_exceeded(spent_usd: float, included_usd: float, upgrade_url: str) -> Problem:
    """402 with the honest reason: the plan's *model time* is gone, not its scan count."""
    return Problem(
        402,
        "budget_exceeded",
        f"This organisation has used the ${included_usd:.2f} of model time included in its "
        f"plan this period (${spent_usd:.2f} spent). The CLI is unaffected and gives the "
        f"same verdict on your own key.",
        spent_usd=round(spent_usd, 4),
        included_usd=included_usd,
        upgrade_url=upgrade_url,
    )


async def reserve(db: AsyncSession, org_id: UUID, plan: Plan, cost_micros: int = 0) -> Usage:
    """Take one scan and its estimated cost out of this period's allowance, or raise 402.

    Must be called inside the same transaction that enqueues the job, and the caller must
    not commit before the enqueue succeeds.
    """
    start = period_start()
    ent = entitlements(plan)
    # Create the row if this is the org's first scan this month, then lock it. The insert
    # is ON CONFLICT DO NOTHING so two first-scans cannot both insert.
    await insert_ignore(
        db,
        Usage,
        {"org_id": org_id, "period_start": start, "scans_used": 0, "cost_micros": 0},
        ["org_id", "period_start"],
    )
    row = (
        await db.execute(
            select(Usage).where(Usage.org_id == org_id, Usage.period_start == start).with_for_update()
        )
    ).scalar_one()

    pricing = f"{settings().web_base_url}/pricing"

    # Money first: it is the limit that decides whether we can afford to run this at all.
    headroom_micros = ent.budget_micros - row.cost_micros
    needed_micros = int(ent.max_cost_usd * MIN_BUDGET_HEADROOM * 1_000_000)
    if headroom_micros < min(needed_micros, ent.budget_micros):
        raise budget_exceeded(row.cost_micros / 1_000_000, ent.included_model_usd, pricing)

    if row.scans_used >= ent.scans_per_month:
        raise quota_exceeded(row.scans_used, ent.scans_per_month, pricing)

    row.scans_used += 1
    row.cost_micros += cost_micros
    await db.flush()
    return row


async def allowed_scan_cost(db: AsyncSession, org_id: UUID, plan: Plan) -> float:
    """The ceiling to hand the engine for one scan.

    The lesser of the plan's per-scan limit, what is left of the period budget, and our own
    global cap. The engine refuses to start a scan whose worst case exceeds this, so an org
    with $0.04 of budget left cannot run a $0.50 scan and leave us holding the difference.
    """
    ent = entitlements(plan)
    row = await current(db, org_id)
    remaining = max(0.0, ent.included_model_usd - row.cost_micros / 1_000_000)
    return min(ent.max_cost_usd, remaining, settings().scan_cost_ceiling_usd)


async def refund(db: AsyncSession, org_id: UUID, cost_micros: int = 0) -> None:
    """Give the reservation back. Only for failures that are ours."""
    start = period_start()
    row = (
        await db.execute(
            select(Usage).where(Usage.org_id == org_id, Usage.period_start == start).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        return
    if row.scans_used > 0:
        row.scans_used -= 1
    if cost_micros:
        # Never below zero: a refund is not a credit towards next period.
        row.cost_micros = max(0, row.cost_micros - cost_micros)
    await db.flush()


async def record_cost(db: AsyncSession, org_id: UUID, cost_micros: int) -> None:
    """Book what a finished scan actually cost.

    This is the number `reserve()` reads next time, so a scan that came in over its
    estimate eats into the same budget instead of being forgotten.
    """
    start = period_start()
    # Create the row if it is missing rather than dropping the cost on the floor. In the
    # normal path `reserve()` made it first, but a cost we fail to book is a cost the next
    # `reserve()` cannot see -- which is exactly the leak this module exists to close.
    await insert_ignore(
        db,
        Usage,
        {"org_id": org_id, "period_start": start, "scans_used": 0, "cost_micros": 0},
        ["org_id", "period_start"],
    )
    row = (
        await db.execute(
            select(Usage).where(Usage.org_id == org_id, Usage.period_start == start).with_for_update()
        )
    ).scalar_one()
    row.cost_micros += cost_micros
    await db.flush()


async def current(db: AsyncSession, org_id: UUID) -> Usage:
    start = period_start()
    row = (
        await db.execute(select(Usage).where(Usage.org_id == org_id, Usage.period_start == start))
    ).scalar_one_or_none()
    return row or Usage(org_id=org_id, period_start=start, scans_used=0, cost_micros=0)


async def has_budget(db: AsyncSession, org_id: UUID, plan: Plan) -> bool:
    """Cheap pre-check for callers that create scans with nobody waiting (monitors)."""
    return await allowed_scan_cost(db, org_id, plan) > 0


async def check_breaker(redis_client: Any, estimated_usd: float) -> None:
    """Global daily spend ceiling across every org.

    Per-org budgets bound what any one customer can cost us; this bounds what all of them
    plus a bug can cost us in a day. If Redis is down we refuse rather than allow: the
    breaker is the last line and it fails closed.
    """
    cfg = settings()
    key = SPEND_KEY + datetime.now(UTC).strftime("%Y-%m-%d")
    try:
        spent_micros = int(await redis_client.get(key) or 0)
    except Exception as exc:
        raise Problem(503, "breaker_unavailable", "Cannot verify the spend limit right now.") from exc
    if spent_micros / 1_000_000 + estimated_usd > cfg.daily_spend_limit_usd:
        raise Problem(
            503,
            "spend_breaker",
            "Hosted scanning is paused for today while we check our usage. "
            "The CLI is unaffected: run the same scan locally with your own key.",
        )


async def add_spend(redis_client: Any, usd: float) -> None:
    key = SPEND_KEY + datetime.now(UTC).strftime("%Y-%m-%d")
    try:
        await redis_client.incrby(key, int(usd * 1_000_000))
        await redis_client.expire(key, int(timedelta(days=3).total_seconds()))
    except Exception:
        # Losing a counter increment is survivable; failing a completed scan is not.
        return
