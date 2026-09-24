"""Cloud test fixtures.

Tests split in two:

- **Offline** (the default): pure logic — SSRF table, webhook signatures, plan maths,
  validation limits, monitor diffs. No containers needed, so they run in CI.
- **`-m db`**: the real stack from cloud/infra/docker-compose.yml. Postgres, because the
  things worth testing here are `SELECT ... FOR UPDATE`, `ON CONFLICT`, JSONB and RLS —
  none of which SQLite has.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any

import pytest

os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("DEV_AUTH_BYPASS", "1")
os.environ.setdefault("BILLING_PROVIDER", "none")
os.environ.setdefault("HEADER_ENC_KEY", "")

#: Postgres when it is there, SQLite when it is not. The models carry dialect
#: variants for exactly this reason: the API suite has to run in CI without a
#: container, and only the tests that are *about* Postgres behaviour (row locking,
#: RLS) are marked `db` and skipped.
PG_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://mcpaudit:mcpaudit@localhost:5432/mcpaudit_test"
)
SQLITE_URL = "sqlite+aiosqlite:///./test.db"


class FakeRedis:
    """Enough Redis for the code paths under test, in a dict.

    A real Redis is not what any of these tests are about, and a fake one keeps the
    offline suite honest about which failures are ours.
    """

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.sets: dict[str, dict[str, float]] = {}
        self.jobs: list[tuple[str, tuple[Any, ...]]] = []

    async def get(self, key: str) -> Any:
        return self.store.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> None:
        self.store[key] = value

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.store.pop(key, None)

    async def incrby(self, key: str, amount: int) -> int:
        self.store[key] = int(self.store.get(key, 0)) + amount
        return int(self.store[key])

    async def expire(self, key: str, seconds: int) -> None:
        return None

    async def ping(self) -> bool:
        return True

    async def zrem(self, key: str, member: str) -> None:
        self.sets.get(key, {}).pop(member, None)

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)

    async def enqueue_job(self, name: str, *args: Any) -> Any:
        self.jobs.append((name, args))
        return type("Job", (), {"job_id": f"job-{len(self.jobs)}"})()


class FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self.ops: list[tuple[str, tuple[Any, ...]]] = []

    def zremrangebyscore(self, key: str, low: float, high: float) -> FakePipeline:
        self.ops.append(("trim", (key, low, high)))
        return self

    def zadd(self, key: str, mapping: dict[str, float]) -> FakePipeline:
        self.ops.append(("add", (key, mapping)))
        return self

    def zcard(self, key: str) -> FakePipeline:
        self.ops.append(("card", (key,)))
        return self

    def expire(self, key: str, seconds: int) -> FakePipeline:
        self.ops.append(("expire", (key, seconds)))
        return self

    async def execute(self) -> list[Any]:
        out: list[Any] = []
        for op, args in self.ops:
            if op == "trim":
                key, low, high = args
                bucket = self.redis.sets.setdefault(key, {})
                for member in [m for m, score in bucket.items() if low <= score <= high]:
                    bucket.pop(member)
                out.append(0)
            elif op == "add":
                key, mapping = args
                self.redis.sets.setdefault(key, {}).update(mapping)
                out.append(1)
            elif op == "card":
                out.append(len(self.redis.sets.get(args[0], {})))
            else:
                out.append(True)
        return out


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture(scope="session")
def event_loop() -> Any:  # pragma: no cover - pytest-asyncio plumbing
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


async def reachable(url: str) -> bool:
    try:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(url)
        async with engine.connect():
            pass
        await engine.dispose()
        return True
    except Exception:
        return False


async def _resolve_url() -> str:
    if await reachable(PG_URL):
        return PG_URL
    return SQLITE_URL


@pytest.fixture(scope="session")
async def database() -> AsyncIterator[str]:
    yield await _resolve_url()


@pytest.fixture(scope="session")
async def postgres(database: str) -> AsyncIterator[str]:
    """For tests that are about Postgres itself: row locking, RLS, JSONB operators."""
    if not database.startswith("postgresql"):
        pytest.skip("needs Postgres: run cloud/infra/docker-compose.yml")
    yield database


@pytest.fixture
async def db(database: str) -> AsyncIterator[Any]:
    """A clean schema per test. Dropping and recreating is fast on an empty database and
    removes any chance of one test's rows explaining another test's pass."""
    os.environ["DATABASE_URL"] = database
    from mcp_audit_cloud.config import settings
    from mcp_audit_cloud.db import create_all, dispose, sessionmaker
    from mcp_audit_cloud.models import Base

    settings.cache_clear()
    await dispose()
    from mcp_audit_cloud.db import engine

    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await create_all()
    async with sessionmaker()() as session:
        yield session
    await dispose()
