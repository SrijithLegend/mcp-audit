"""arq worker: rug-pull monitoring and retention. **Never inference.**

This process holds no LLM key and imports nothing from the engine that could call one
(`tests/test_invariants.py` greps for it). What it does is the half of monitoring that needs
no model at all:

    capture tools/list  ->  hash it  ->  compare  ->  tell the customer what moved

Which is most of the value, and it costs nothing. Deciding whether the *new* text steers a
model does need inference, so that runs where the key is: the customer's CI, on their
schedule, pushing the report back to us. The alert says exactly that, with the command.
"""

from __future__ import annotations

import contextlib
from typing import Any, ClassVar
from uuid import UUID

import structlog
from arq.connections import RedisSettings
from mcp_audit.errors import AuditError
from sqlalchemy import select

from .config import settings
from .db import dispose, sessionmaker, set_org
from .models import Monitor
from .services import monitors as monitor_service

log = structlog.get_logger()

#: A capture is one HTTP round trip and a hash. Nothing here should take minutes.
JOB_TIMEOUT = 120
MAX_TRIES = 3


async def check_monitor(ctx: dict[str, Any], monitor_id: str) -> str:
    """Capture a monitored target and compare hashes. This is the rug-pull feature."""
    async with sessionmaker()() as db:
        monitor = (
            await db.execute(select(Monitor).where(Monitor.id == UUID(monitor_id)))
        ).scalar_one_or_none()
        if monitor is None or not monitor.enabled:
            return "skipped"
        await set_org(db, monitor.org_id)
        try:
            return await monitor_service.check(db, ctx["redis"], monitor)
        except AuditError as exc:
            # A target that will not answer is the customer's to fix, and monitors.check
            # already records the failure and eventually pauses the monitor.
            log.info("monitor.unreachable", monitor_id=monitor_id, error=str(exc)[:200])
            await db.commit()
            return "error"


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
    functions: ClassVar[list[Any]] = [check_monitor, sweep_monitors, expire_data]
    on_startup = startup
    on_shutdown = shutdown
    job_timeout = JOB_TIMEOUT
    max_tries = MAX_TRIES
    retry_jobs = True
    max_jobs = 8

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
