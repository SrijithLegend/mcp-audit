"""Retention: delete what the plan no longer covers (docs/SECURITY.md §10).

Hard deletes, not soft ones. "Retention: 7 days" has to mean the rows are gone, or the
privacy policy is a lie. Runs nightly from the worker.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import InventoryChange, InventoryRow, Org, Scan
from ..plans import entitlements

log = structlog.get_logger()


async def purge(db: AsyncSession, now: datetime | None = None) -> int:
    """Delete expired scans and the change history behind them, per org plan."""
    at = now or datetime.now(UTC)
    removed = 0
    orgs = (await db.execute(select(Org))).scalars().all()
    for org in orgs:
        cutoff = at - timedelta(days=entitlements(org.plan).retention_days)
        # synchronize_session=False: let the database do the comparison. The ORM's
        # in-Python evaluation trips over naive-vs-aware datetimes, and a retention
        # sweep has no session state worth synchronising anyway.
        result = await db.execute(
            delete(Scan).where(Scan.org_id == org.id, Scan.created_at < cutoff),
            execution_options={"synchronize_session": False},
        )
        removed += int(getattr(result, "rowcount", 0) or 0)
        await db.execute(
            delete(InventoryChange).where(
                InventoryChange.org_id == org.id, InventoryChange.created_at < cutoff
            ),
            execution_options={"synchronize_session": False},
        )
    # Inventories nothing references any more: they are the customer's tool names and
    # we said we would not keep them longer than we need them.
    await db.execute(
        delete(InventoryRow).where(
            InventoryRow.id.not_in(select(Scan.inventory_id).where(Scan.inventory_id.is_not(None))),
            InventoryRow.created_at < at - timedelta(days=2),
        ),
        execution_options={"synchronize_session": False},
    )
    return removed


async def delete_org_data(db: AsyncSession, org_id: UUID) -> None:
    """Account deletion. Billing records are kept only as the MoR requires."""
    from ..models import ApiToken, Monitor, Target

    for model in (Scan, InventoryChange, Monitor, Target, InventoryRow, ApiToken):
        await db.execute(
            delete(model).where(model.org_id == org_id),
            execution_options={"synchronize_session": False},
        )
    log.info("org.data_deleted", org_id=str(org_id))
