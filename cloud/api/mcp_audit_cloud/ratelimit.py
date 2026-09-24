"""Redis sliding-window rate limits (docs/SECURITY.md §6).

Sliding window, not a fixed bucket: a fixed window lets a caller spend the whole
allowance in the last second of one window and again in the first second of the next.

The counter is a sorted set of request timestamps per key, trimmed on every check, all
in one pipeline so two concurrent requests cannot both see room for one more.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from redis.asyncio import Redis

from .config import settings
from .errors import rate_limited

_redis: Redis | None = None


def redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings().redis_url, decode_responses=True)
    return _redis


async def close() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
    _redis = None


async def hit(key: str, limit: int, window_seconds: int, redis_client: Any | None = None) -> None:
    """Record one request against `key`; raise 429 when the window is full.

    A Redis outage must not take the API down with it: if the limiter cannot be
    reached we allow the request. The quota reservation and the spend breaker are the
    controls that protect money, and those are in Postgres.
    """
    client = redis_client or redis()
    now = time.time()
    # A random suffix, not id(object()): CPython reuses addresses for temporaries, so
    # two hits in the same microsecond would collide and one would not be counted.
    member = f"{now}:{secrets.token_hex(8)}"
    try:
        pipe = client.pipeline()
        pipe.zremrangebyscore(key, 0, now - window_seconds)
        pipe.zadd(key, {member: now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds + 1)
        _, _, count, _ = await pipe.execute()
    except Exception:
        return
    if int(count) > limit:
        await client.zrem(key, member)
        raise rate_limited(window_seconds)


async def anon(ip: str, redis_client: Any | None = None) -> None:
    await hit(f"rl:anon:{ip}", settings().rate_limit_anon_per_min, 60, redis_client)


async def org(org_id: str, redis_client: Any | None = None) -> None:
    await hit(f"rl:org:{org_id}", settings().rate_limit_org_per_min, 60, redis_client)


async def scan_creation(org_id: str, redis_client: Any | None = None) -> None:
    await hit(f"rl:scan:{org_id}", settings().rate_limit_scans_per_min, 60, redis_client)


async def token_creation(org_id: str, redis_client: Any | None = None) -> None:
    await hit(f"rl:token:{org_id}", settings().rate_limit_tokens_per_hour, 3600, redis_client)


async def shared_view(ip: str, redis_client: Any | None = None) -> None:
    await hit(f"rl:shared:{ip}", settings().rate_limit_shared_per_min, 60, redis_client)
