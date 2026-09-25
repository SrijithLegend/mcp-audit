"""Usage limits. Anti-abuse and storage, not money.

Scans run on the user's own key, wherever they already keep it, and the Cloud only ingests
the finished report (D12'). So there is no inference bill to hedge: what these limits bound
is our database, our queue and our bandwidth.

The race still matters, for a different reason. 50 uploads arriving at once against a limit
of 5 must accept exactly 5, or the limit is decorative. So the usage row is locked with
`SELECT ... FOR UPDATE` and incremented inside the same transaction as the check.

`cost_micros` is still recorded, but it is now **the customer's** spend, read off the report
they uploaded. We keep it because it is genuinely useful to them -- "these audits cost you
$4.10 this month" -- and because it is the number that tells us what a scan really costs
when Gate 1 comes around. It is never a limit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import insert_ignore
from ..errors import Problem
from ..models import Plan, Usage
from ..plans import entitlements


def period_start(now: datetime | None = None) -> datetime:
    """Calendar month. Simple, predictable, and what the pricing page says."""
    at = now or datetime.now(UTC)
    return at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def limit_reached(used: int, limit: int, upgrade_url: str) -> Problem:
    return Problem(
        402,
        "limit_reached",
        f"This organisation has stored {used} of {limit} reports this period. Scanning itself "
        f"is unaffected -- the CLI runs on your own key and is free and unlimited.",
        used=used,
        limit=limit,
        upgrade_url=upgrade_url,
    )


async def reserve(db: AsyncSession, org_id: UUID, plan: Plan) -> Usage:
    """Take one report out of this period's allowance, or raise 402.

    Must be called in the same transaction that stores the report, so a concurrent upload
    cannot see the same headroom twice.
    """
    start = period_start()
    ent = entitlements(plan)
    # Create the row if this is the org's first upload this month, then lock it. The insert
    # is ON CONFLICT DO NOTHING so two first-uploads cannot both insert.
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

    if row.scans_used >= ent.reports_per_month:
        raise limit_reached(row.scans_used, ent.reports_per_month, f"{settings().web_base_url}/pricing")

    row.scans_used += 1
    await db.flush()
    return row


async def release(db: AsyncSession, org_id: UUID) -> None:
    """Give the reservation back when storing the report failed on our side."""
    start = period_start()
    row = (
        await db.execute(
            select(Usage).where(Usage.org_id == org_id, Usage.period_start == start).with_for_update()
        )
    ).scalar_one_or_none()
    if row is not None and row.scans_used > 0:
        row.scans_used -= 1
        await db.flush()


async def record_customer_cost(db: AsyncSession, org_id: UUID, cost_micros: int) -> None:
    """Book what the *customer* spent on their own key, as reported by their CLI.

    Informational: it is their bill, and showing it back to them is the point. It never
    gates anything, which is why there is no check here.
    """
    start = period_start()
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
    row.cost_micros += max(0, cost_micros)
    await db.flush()


async def current(db: AsyncSession, org_id: UUID) -> Usage:
    start = period_start()
    row = (
        await db.execute(select(Usage).where(Usage.org_id == org_id, Usage.period_start == start))
    ).scalar_one_or_none()
    return row or Usage(org_id=org_id, period_start=start, scans_used=0, cost_micros=0)
