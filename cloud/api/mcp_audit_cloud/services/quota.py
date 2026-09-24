"""Quota reservation and the global spend breaker (invariant 7).

The race that matters: 50 scan submissions arriving at once against a quota of 10 must
accept exactly 10. Checking-then-incrementing in two statements accepts about 50. So the
usage row is locked with `SELECT ... FOR UPDATE` and incremented inside the same
transaction as the check, *before* the job is enqueued.

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


def period_start(now: datetime | None = None) -> datetime:
    """Calendar month. Simple, predictable, and what the pricing page says."""
    at = now or datetime.now(UTC)
    return at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def reserve(db: AsyncSession, org_id: UUID, plan: Plan, cost_micros: int = 0) -> Usage:
    """Take one scan out of this period's allowance, or raise 402.

    Must be called inside the same transaction that enqueues the job, and the caller
    must not commit before the enqueue succeeds.
    """
    start = period_start()
    # Create the row if this is the org's first scan this month, then lock it. The
    # insert is ON CONFLICT DO NOTHING so two first-scans cannot both insert.
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

    limit = entitlements(plan).scans_per_month
    if row.scans_used >= limit:
        raise quota_exceeded(row.scans_used, limit, f"{settings().web_base_url}/pricing")
    row.scans_used += 1
    row.cost_micros += cost_micros
    await db.flush()
    return row


async def refund(db: AsyncSession, org_id: UUID) -> None:
    """Give the reservation back. Only for failures that are ours."""
    start = period_start()
    row = (
        await db.execute(
            select(Usage).where(Usage.org_id == org_id, Usage.period_start == start).with_for_update()
        )
    ).scalar_one_or_none()
    if row is not None and row.scans_used > 0:
        row.scans_used -= 1
        await db.flush()


async def record_cost(db: AsyncSession, org_id: UUID, cost_micros: int) -> None:
    start = period_start()
    row = (
        await db.execute(
            select(Usage).where(Usage.org_id == org_id, Usage.period_start == start).with_for_update()
        )
    ).scalar_one_or_none()
    if row is not None:
        row.cost_micros += cost_micros
        await db.flush()


async def current(db: AsyncSession, org_id: UUID) -> Usage:
    start = period_start()
    row = (
        await db.execute(select(Usage).where(Usage.org_id == org_id, Usage.period_start == start))
    ).scalar_one_or_none()
    return row or Usage(org_id=org_id, period_start=start, scans_used=0, cost_micros=0)


async def check_breaker(redis_client: Any, estimated_usd: float) -> None:
    """Global daily spend ceiling across every org.

    Quota is per customer; this is the one that stops a bug -- ours or theirs -- from
    turning into a five-figure Anthropic bill overnight. If Redis is down we refuse
    rather than allow: the breaker is the last line and it fails closed.
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
