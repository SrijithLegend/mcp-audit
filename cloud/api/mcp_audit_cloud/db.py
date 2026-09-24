"""Async engine, sessions, and the org scoping that authorisation rests on.

Two walls (docs/SECURITY.md §5):

1. `scoped()` -- every org query goes through a helper that takes the org id from the
   authenticated principal. Never from the request body.
2. Postgres RLS -- the session sets `app.org_id` per transaction, and the policies only
   let rows with that org through. If wall 1 has a bug, wall 2 still returns nothing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import Select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import settings
from .models import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

T = TypeVar("T")


def engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings().database_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=10,
            echo=False,
        )
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(engine(), expire_on_commit=False, class_=AsyncSession)
    return _sessionmaker


async def session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. One transaction per request, rolled back on an exception."""
    async with sessionmaker()() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def set_org(db: AsyncSession, org_id: UUID | None) -> None:
    """Bind this transaction to an org so the RLS policies can see it.

    Parameterised, not formatted: `set_config` takes the value as a bind parameter,
    because an org id that reached here as a string from somewhere unexpected must not
    be able to end a statement (invariant 5).

    A no-op on anything but Postgres. RLS is the *second* wall -- the repository layer
    is the first one and it works everywhere -- so the test suite running on SQLite
    still exercises the real authorisation path.
    """
    if db.get_bind().dialect.name != "postgresql":
        return
    await db.execute(
        text("SELECT set_config('app.org_id', :org, true)"),
        {"org": str(org_id) if org_id else ""},
    )


def scoped(statement: Select[Any], model: Any, org_id: UUID) -> Select[Any]:
    """The only sanctioned way to query an org-scoped table.

    Taking `org_id` as an argument rather than reading it from a request is the whole
    point: a handler that forgets it does not compile into something permissive, it
    fails to call this at all -- and the IDOR suite catches that.
    """
    return statement.where(model.org_id == org_id)


async def insert_ignore(db: AsyncSession, model: Any, values: dict[str, Any], conflict: list[str]) -> int:
    """INSERT ... ON CONFLICT DO NOTHING, on whichever database we are on.

    Postgres in production, SQLite in the test suite (no container needed). Both
    support the clause; only the import differs, and doing this in one helper keeps
    every call site from having to care.
    """
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        statement: Any = pg_insert(model).values(**values).on_conflict_do_nothing(index_elements=conflict)
    else:
        from sqlalchemy.dialects.sqlite import insert as lite_insert

        statement = lite_insert(model).values(**values).on_conflict_do_nothing(index_elements=conflict)
    result = await db.execute(statement)
    return int(getattr(result, "rowcount", 0) or 0)


async def create_all() -> None:
    """Local development and tests only. Production schema comes from Alembic."""
    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
