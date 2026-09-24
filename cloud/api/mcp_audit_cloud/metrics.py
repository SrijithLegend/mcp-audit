"""The five numbers worth alerting on (ROADMAP Phase 7).

Deliberately not a Prometheus exporter. This service runs on two small machines; a
`/metrics` endpoint would be a second thing to secure and scrape for numbers that the logs
and one SQL query already carry. What exists instead:

- structured log events with stable names, so the log platform can count them;
- one endpoint that reports queue depth and scan latency for the alerting rules below.

If this ever grows past a few machines, replace this file with a real exporter — do not
grow it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Scan, ScanStatus

#: Alert rules, written here rather than only in a dashboard so they are reviewable in a
#: pull request. Values are the ones ROADMAP Phase 7 asks for.
ALERTS = (
    ("queue_depth", "> 50 for 10 minutes", "workers are down or every job is failing"),
    ("spend_breaker_tripped", "any", "hosted scanning is refusing work; see runbooks/spend-spike.md"),
    ("webhook_failure_rate", "> 5% over 1 hour", "a customer's receiver is down, or ours is misconfigured"),
    ("api_5xx_rate", "> 1% over 5 minutes", "bad deploy or dependency outage"),
    ("scan_p95_seconds", "> 300 for 15 minutes", "trials are hitting max_turns or the API is slow"),
    (
        "stuck_scans",
        "any scan queued > 10 minutes",
        "enqueue failed silently; see runbooks/webhook-backlog.md",
    ),
)


async def snapshot(db: AsyncSession, redis: Any) -> dict[str, Any]:
    """Current values for the alert rules. Cheap enough to poll every 30 seconds."""
    now = datetime.now(UTC)
    hour_ago = now - timedelta(hours=1)

    queued, running = (
        await db.execute(
            select(
                func.count().filter(Scan.status == ScanStatus.QUEUED),
                func.count().filter(Scan.status == ScanStatus.RUNNING),
            )
        )
    ).one()

    stuck = (
        await db.execute(
            select(func.count()).where(
                Scan.status == ScanStatus.QUEUED, Scan.queued_at < now - timedelta(minutes=10)
            )
        )
    ).scalar_one()

    finished = (
        await db.execute(
            select(
                func.count(),
                func.avg(func.extract("epoch", Scan.finished_at) - func.extract("epoch", Scan.started_at)),
                func.sum(Scan.cost_micros),
            ).where(Scan.finished_at.is_not(None), Scan.finished_at > hour_ago)
        )
    ).one()

    failed = (
        await db.execute(
            select(func.count()).where(Scan.status == ScanStatus.FAILED, Scan.finished_at > hour_ago)
        )
    ).scalar_one()

    spent_today = 0
    try:
        key = "breaker:spend:" + now.strftime("%Y-%m-%d")
        spent_today = int(await redis.get(key) or 0)
    except Exception:
        spent_today = -1

    count, mean_seconds, cost_micros = finished
    return {
        "queue_depth": int(queued or 0),
        "running": int(running or 0),
        "stuck_scans": int(stuck or 0),
        "scans_last_hour": int(count or 0),
        "failed_last_hour": int(failed or 0),
        "mean_scan_seconds": round(float(mean_seconds or 0), 1),
        "cost_last_hour_usd": round(int(cost_micros or 0) / 1_000_000, 4),
        "spend_today_usd": round(spent_today / 1_000_000, 4) if spent_today >= 0 else None,
        "alerts": [{"name": name, "threshold": rule, "meaning": why} for name, rule, why in ALERTS],
    }
