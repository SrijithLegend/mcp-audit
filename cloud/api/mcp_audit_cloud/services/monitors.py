"""Rug-pull detection: capture, compare hashes, scan on change, tell the customer.

This is the feature that justifies a subscription rather than a one-off payment, so it
gets the care: the diff is structural *and* textual, the auto-scan is attributed to the
monitor, and a target that starts failing pauses itself instead of retrying forever.

A monitor narrows the rug-pull window; it does not close it. The README says so.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from mcp_audit.capture.http import capture_http
from mcp_audit.errors import AuditError
from mcp_audit.models import Inventory
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import Problem
from ..models import InventoryChange, Monitor, Plan, Scan, ScanStatus, Target, TargetKind
from ..plans import entitlements
from . import notify, quota, scans, secrets

log = structlog.get_logger()

#: A target that has been unreachable this many checks running gets paused. Retrying a
#: dead endpoint every hour forever is how you get blocked by somebody's WAF.
FAILURES_BEFORE_PAUSE = 5


async def due(db: AsyncSession, now: datetime | None = None) -> list[Monitor]:
    """Monitors whose plan interval has elapsed.

    Plan decides the cadence, so a downgrade slows a monitor down rather than deleting
    it (ROADMAP §5.2: downgrade never deletes data).
    """
    at = now or datetime.now(UTC)
    rows = (await db.execute(select(Monitor).where(Monitor.enabled.is_(True)))).scalars().all()
    ready = []
    for monitor in rows:
        org_plan = await _plan(db, monitor.org_id)
        interval = entitlements(org_plan).monitor_min_interval_minutes
        if interval <= 0:
            continue  # the plan has no monitoring; it stays paused, not removed
        if monitor.last_checked_at is None or monitor.last_checked_at <= at - timedelta(minutes=interval):
            ready.append(monitor)
    return ready


async def _plan(db: AsyncSession, org_id: UUID) -> Plan:
    from ..models import Org

    org = (await db.execute(select(Org).where(Org.id == org_id))).scalar_one()
    return org.plan


async def check(db: AsyncSession, redis: Any, monitor: Monitor) -> str:
    """Capture the target and act on what changed."""
    target = (await db.execute(select(Target).where(Target.id == monitor.target_id))).scalar_one_or_none()
    if target is None or target.kind is not TargetKind.REMOTE_HTTP or not target.url:
        monitor.enabled = False
        monitor.paused_reason = "target is not a remote HTTP endpoint"
        await db.flush()
        return "paused"

    monitor.last_checked_at = datetime.now(UTC)
    try:
        inventory = await _capture(db, monitor, target)
    except AuditError as exc:
        return await _record_failure(db, monitor, str(exc))

    digest = inventory.sha256()
    if monitor.last_sha256 == digest:
        monitor.last_status = "unchanged"
        await db.flush()
        return "unchanged"

    first_time = monitor.last_sha256 is None
    previous = await _previous_inventory(db, monitor)
    row = await scans.upsert_inventory(db, monitor.org_id, inventory)

    plan = await _plan(db, monitor.org_id)
    # A monitor-triggered scan costs exactly what a user-triggered one costs, so it takes
    # a reservation like any other. Without this, monitors were an unmetered way to spend
    # our model budget -- ten daily monitors is ~300 free scans a month.
    try:
        await quota.reserve(db, monitor.org_id, plan)
    except Problem as exc:
        # Record the change anyway: knowing the server moved is the valuable half, and it
        # costs nothing. We just cannot afford to re-scan it right now.
        await _record_change(db, monitor, previous, inventory, digest, scan_id=None)
        monitor.last_status = f"changed:unscanned:{exc.code}"
        await db.flush()
        await db.commit()
        await notify.inventory_changed(db, monitor, await _latest_change(db, monitor))
        log.info("monitor.changed_but_over_budget", monitor_id=str(monitor.id), reason=exc.code)
        return "changed_unscanned"

    scan = Scan(
        org_id=monitor.org_id,
        target_id=target.id,
        inventory_id=row.id,
        status=ScanStatus.QUEUED,
        trials=entitlements(await _plan(db, monitor.org_id)).max_trials,
        model=_model(),
        task=target.task,
        created_via="monitor",
        queued_at=datetime.now(UTC),
    )
    db.add(scan)
    await db.flush()

    change = await _record_change(db, monitor, previous, inventory, digest, scan_id=scan.id)
    monitor.last_status = "first_capture" if first_time else "changed"
    await db.flush()
    await db.commit()

    await redis.enqueue_job("run_scan", str(scan.id))
    if not first_time:
        await notify.inventory_changed(db, monitor, change)
    return monitor.last_status


async def _record_change(
    db: AsyncSession,
    monitor: Monitor,
    previous: Inventory | None,
    inventory: Inventory,
    digest: str,
    scan_id: Any,
) -> InventoryChange:
    """Store what moved. Cheap, and worth doing even when we cannot afford to re-scan."""
    change = InventoryChange(
        monitor_id=monitor.id,
        org_id=monitor.org_id,
        old_sha256=monitor.last_sha256,
        new_sha256=digest,
        diff=diff(previous, inventory),
        scan_id=scan_id,
    )
    db.add(change)
    monitor.last_sha256 = digest
    await db.flush()
    return change


async def _latest_change(db: AsyncSession, monitor: Monitor) -> InventoryChange:
    return (
        await db.execute(
            select(InventoryChange)
            .where(InventoryChange.monitor_id == monitor.id)
            .order_by(InventoryChange.id.desc())
            .limit(1)
        )
    ).scalar_one()


async def _capture(db: AsyncSession, monitor: Monitor, target: Target) -> Inventory:
    from ..ssrf import guarded_client

    headers = await secrets.load_for_target(db, monitor.org_id, target.id)
    client = guarded_client(str(target.url), headers=headers)
    try:
        return await capture_http(str(target.url), client=client)
    finally:
        await client.aclose()


async def _previous_inventory(db: AsyncSession, monitor: Monitor) -> Inventory | None:
    from ..models import InventoryRow

    if not monitor.last_sha256:
        return None
    row = (
        await db.execute(
            select(InventoryRow).where(
                InventoryRow.org_id == monitor.org_id, InventoryRow.sha256 == monitor.last_sha256
            )
        )
    ).scalar_one_or_none()
    return Inventory.model_validate(row.content) if row else None


async def _record_failure(db: AsyncSession, monitor: Monitor, error: str) -> str:
    failures = 1
    if monitor.last_status and monitor.last_status.startswith("error:"):
        try:
            failures = int(monitor.last_status.split(":")[1]) + 1
        except (IndexError, ValueError):
            failures = 1
    monitor.last_status = f"error:{failures}:{error[:120]}"
    if failures >= FAILURES_BEFORE_PAUSE:
        monitor.enabled = False
        monitor.paused_reason = f"unreachable {failures} checks running"
    await db.flush()
    log.info("monitor.error", monitor_id=str(monitor.id), failures=failures, error=error[:200])
    return "error"


def _model() -> str:
    from mcp_audit.harness import MODEL

    return str(MODEL)


def diff(old: Inventory | None, new: Inventory) -> dict[str, Any]:
    """What changed, in the shape the UI renders.

    Structural changes (a tool appeared, a parameter appeared) and prose changes are
    separated, because they mean different things: a new tool is a feature, a rewritten
    description with the same call surface is the rug-pull shape.
    """
    if old is None:
        return {"first_capture": True, "tools_added": [t.name for t in new.tools]}

    old_tools = {t.name: t for t in old.tools}
    new_tools = {t.name: t for t in new.tools}
    prose_changed = []
    schema_changed = []
    for name, tool in new_tools.items():
        was = old_tools.get(name)
        if was is None:
            continue
        if was.description != tool.description:
            prose_changed.append(
                {
                    "tool": name,
                    "before": was.description[:2000],
                    "after": tool.description[:2000],
                }
            )
        if was.input_schema != tool.input_schema:
            schema_changed.append(
                {
                    "tool": name,
                    "params_before": was.param_names(),
                    "params_after": tool.param_names(),
                    "required_before": was.required(),
                    "required_after": tool.required(),
                }
            )
    return {
        "first_capture": False,
        "instructions_changed": old.instructions != new.instructions,
        "instructions_before": old.instructions[:4000],
        "instructions_after": new.instructions[:4000],
        "tools_added": sorted(set(new_tools) - set(old_tools)),
        "tools_removed": sorted(set(old_tools) - set(new_tools)),
        "prose_changed": prose_changed,
        "schema_changed": schema_changed,
        "version_before": old.server_version,
        "version_after": new.server_version,
    }
