"""Enqueueing jobs. One place, so the API never constructs an arq pool per request."""

from __future__ import annotations

from typing import Any

import structlog
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from .config import settings

log = structlog.get_logger()

_pool: ArqRedis | None = None


async def pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(settings().redis_url))
    return _pool


async def enqueue(job: str, *args: Any) -> str | None:
    """Fire a job. A queue that is briefly unavailable must not lose the row.

    The scan is already persisted as `queued` when we get here, so a failed enqueue is
    recoverable: the sweeper picks up anything that has sat in `queued` too long.
    """
    try:
        handle = await (await pool()).enqueue_job(job, *args)
    except Exception as exc:
        log.error("queue.enqueue_failed", job=job, error=str(exc)[:200])
        return None
    return handle.job_id if handle else None


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
    _pool = None
