"""arq worker: runs scans and monitors.

This is the only process that holds our Anthropic key, and the only one that talks to a
customer's MCP server — always over https, always through the SSRF guard, never by
spawning anything (invariant 3).
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID

import structlog
from arq.connections import RedisSettings
from mcp_audit.audit import audit
from mcp_audit.capture.http import capture_http
from mcp_audit.errors import ApiError, AuditError
from mcp_audit.harness import DEFAULT_TASK, client
from mcp_audit.models import Inventory
from sqlalchemy import select

from .config import settings
from .db import dispose, sessionmaker, set_org
from .models import InventoryRow, Monitor, Scan, ScanStatus, Target, TargetKind
from .services import monitors as monitor_service
from .services import notify, quota, scans, secrets

log = structlog.get_logger()

JOB_TIMEOUT = 600
MAX_TRIES = 3


async def run_scan(ctx: dict[str, Any], scan_id: str) -> str:
    """One hosted scan. Every exit path leaves the row in a terminal state."""
    redis = ctx["redis"]
    async with sessionmaker()() as db:
        scan = (await db.execute(select(Scan).where(Scan.id == UUID(scan_id)))).scalar_one_or_none()
        if scan is None:
            return "gone"
        await set_org(db, scan.org_id)
        if scan.status in (ScanStatus.SUCCEEDED, ScanStatus.CANCELED, ScanStatus.FAILED):
            return scan.status.value
        if scan.cancel_requested:
            scan.status = ScanStatus.CANCELED
            scan.finished_at = datetime.now(UTC)
            await db.commit()
            return "canceled"

        scan.status = ScanStatus.RUNNING
        scan.started_at = datetime.now(UTC)
        await db.commit()

        try:
            inventory = await _inventory_for(db, redis, scan)
            report = await audit(
                inventory,
                api=client(settings().anthropic_api_key or None),
                task=scan.task or DEFAULT_TASK,
                trials=scan.trials,
                model=scan.model,
                stub_mode="inert" if scan.stub_mode == "inert" else "canary",
                max_cost=settings().scan_cost_ceiling_usd,
                assume_yes=False,
                interactive=False,
            )
        except ApiError as exc:
            # Ours, not theirs: give the quota reservation back.
            await _fail(db, scan, "api_error", str(exc))
            await quota.refund(db, scan.org_id)
            await db.commit()
            log.warning("scan.api_error", scan_id=scan_id, error=str(exc))
            raise
        except AuditError as exc:
            await _fail(db, scan, "capture_error", str(exc))
            await db.commit()
            log.info("scan.failed", scan_id=scan_id, error=str(exc))
            return "failed"
        except Exception as exc:
            await _fail(db, scan, "internal_error", f"{type(exc).__name__}")
            await quota.refund(db, scan.org_id)
            await db.commit()
            log.exception("scan.crashed", scan_id=scan_id)
            raise

        await scans.persist_report(db, scan, report)
        await quota.record_cost(db, scan.org_id, scan.cost_micros)
        await quota.add_spend(redis, report.usage.cost_usd)
        await db.commit()
        await notify.scan_completed(db, scan)
        log.info("scan.done", scan_id=scan_id, verdict=scan.verdict, cost_micros=scan.cost_micros)
        return scan.verdict or "done"


async def _inventory_for(db: Any, redis: Any, scan: Scan) -> Inventory:
    """Uploaded inventory, or a fresh capture of a remote target.

    Capture happens here rather than in the request so a slow server cannot hold an API
    worker open, and so the SSRF guard runs in the process that actually dials out.
    """
    if scan.inventory_id is not None:
        row = (
            await db.execute(select(InventoryRow).where(InventoryRow.id == scan.inventory_id))
        ).scalar_one()
        return Inventory.model_validate(row.content)

    target = (await db.execute(select(Target).where(Target.id == scan.target_id))).scalar_one()
    if target.kind is not TargetKind.REMOTE_HTTP or not target.url:
        raise AuditError("This target has no inventory and no URL to capture from.")

    headers = await secrets.take_one_off(redis, scan.id)
    if not headers:
        headers = await secrets.load_for_target(db, scan.org_id, target.id)

    from .ssrf import guarded_client  # imported here so the API process need not resolve DNS

    api = guarded_client(target.url, headers=headers)
    try:
        inventory = await capture_http(target.url, client=api)
    finally:
        await api.aclose()
    row = await scans.upsert_inventory(db, scan.org_id, inventory)
    scan.inventory_id = row.id
    await db.flush()
    return inventory


async def _fail(db: Any, scan: Scan, code: str, detail: str) -> None:
    scan.status = ScanStatus.FAILED
    scan.error_code = code
    scan.error_detail = detail[:1000]
    scan.finished_at = datetime.now(UTC)


async def check_monitor(ctx: dict[str, Any], monitor_id: str) -> str:
    """Capture a monitored target and compare hashes. This is the rug-pull feature."""
    async with sessionmaker()() as db:
        monitor = (
            await db.execute(select(Monitor).where(Monitor.id == UUID(monitor_id)))
        ).scalar_one_or_none()
        if monitor is None or not monitor.enabled:
            return "skipped"
        await set_org(db, monitor.org_id)
        return await monitor_service.check(db, ctx["redis"], monitor)


async def sweep_monitors(ctx: dict[str, Any]) -> int:
    """Cron entry point: enqueue every monitor that is due."""
    async with sessionmaker()() as db:
        due = await monitor_service.due(db)
        for monitor in due:
            await ctx["redis"].enqueue_job("check_monitor", str(monitor.id))
        return len(due)


async def expire_data(ctx: dict[str, Any]) -> int:
    """Nightly retention sweep (docs/SECURITY.md §10). Deletes, not archives."""
    from .services import retention

    async with sessionmaker()() as db:
        removed = await retention.purge(db)
        await db.commit()
        log.info("retention.purged", scans=removed)
        return removed


async def startup(ctx: dict[str, Any]) -> None:
    if settings().sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(dsn=settings().sentry_dsn, environment=settings().environment)
    log.info("worker.start", environment=settings().environment)


async def shutdown(ctx: dict[str, Any]) -> None:
    await dispose()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [run_scan, check_monitor, sweep_monitors, expire_data]
    on_startup = startup
    on_shutdown = shutdown
    job_timeout = JOB_TIMEOUT
    max_tries = MAX_TRIES
    # Retry only helps transient API failures; a bad inventory fails the same way twice.
    retry_jobs = True
    max_jobs = 4

    @property
    def redis_settings(self) -> RedisSettings:  # pragma: no cover - arq reads this
        return RedisSettings.from_dsn(settings().redis_url)

    cron_jobs: ClassVar[list[Any]] = []


def _cron() -> list[Any]:
    from arq import cron

    return [
        cron(sweep_monitors, minute={0, 15, 30, 45}, run_at_startup=False),
        cron(expire_data, hour=3, minute=20),
    ]


with contextlib.suppress(Exception):  # pragma: no cover - arq's cron API may move
    WorkerSettings.cron_jobs = _cron()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(sweep_monitors({"redis": None}))
