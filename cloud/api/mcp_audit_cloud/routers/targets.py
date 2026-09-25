"""/v1/targets and /v1/monitors.

Header values are write-only here: they go in encrypted and the API never shows them
again, only their names (docs/SECURITY.md §4).
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import Principal, principal
from ..db import scoped, session
from ..errors import Problem, not_found
from ..models import InventoryChange, Monitor, Role, Target, TargetKind
from ..schemas import ChangeOut, MonitorCreate, MonitorOut, Page, TargetCreate, TargetOut
from ..services import secrets
from ..ssrf import validate as ssrf_validate

router = APIRouter(prefix="/v1", tags=["targets"])


@router.post("/targets", response_model=TargetOut, status_code=201)
async def create_target(
    body: TargetCreate,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> TargetOut:
    who.require(Role.OWNER, Role.ADMIN)
    count = (await db.execute(scoped(select(func.count(Target.id)), Target, who.org_id))).scalar_one()
    if count >= who.entitlements.targets:
        raise Problem(
            402,
            "limit_reached",
            f"This plan allows {who.entitlements.targets} targets.",
        )
    if body.kind == "remote_http":
        if not body.url:
            raise Problem(422, "invalid_request", "A remote_http target needs a url.")
        # Fail now, not in a worker: the user is standing right here.
        ssrf_validate(body.url)

    target = Target(
        org_id=who.org_id,
        kind=TargetKind(body.kind),
        name=body.name,
        url=body.url,
        task=body.task,
        header_names=[],
    )
    db.add(target)
    await db.flush()
    if body.headers:
        target.header_names = await secrets.store_for_target(db, who.org_id, target.id, body.headers)
    return TargetOut.model_validate(target)


@router.get("/targets", response_model=Page[TargetOut])
async def list_targets(
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> Page[TargetOut]:
    statement = scoped(select(Target), Target, who.org_id).order_by(Target.id.desc()).limit(limit + 1)
    if cursor:
        statement = statement.where(Target.id < UUID(cursor))
    rows = list((await db.execute(statement)).scalars())
    return Page(
        items=[TargetOut.model_validate(r) for r in rows[:limit]],
        next_cursor=str(rows[limit - 1].id) if rows[limit:] else None,
    )


@router.patch("/targets/{target_id}", response_model=TargetOut)
async def update_target(
    target_id: UUID,
    body: TargetCreate,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> TargetOut:
    who.require(Role.OWNER, Role.ADMIN)
    target = await _target(db, who, target_id)
    if body.url and body.url != target.url:
        ssrf_validate(body.url)
        target.url = body.url
    target.name = body.name or target.name
    target.task = body.task
    if body.headers is not None:
        target.header_names = await secrets.store_for_target(db, who.org_id, target.id, body.headers)
    return TargetOut.model_validate(target)


@router.delete("/targets/{target_id}", status_code=204)
async def delete_target(
    target_id: UUID,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> Response:
    who.require(Role.OWNER, Role.ADMIN)
    await db.delete(await _target(db, who, target_id))
    return Response(status_code=204)


@router.post("/monitors", response_model=MonitorOut, status_code=201)
async def create_monitor(
    body: MonitorCreate,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> MonitorOut:
    who.require(Role.OWNER, Role.ADMIN)
    ent = who.entitlements
    if ent.monitors == 0:
        raise Problem(402, "upgrade_required", "Monitoring is a Pro feature.")
    count = (await db.execute(scoped(select(func.count(Monitor.id)), Monitor, who.org_id))).scalar_one()
    if count >= ent.monitors:
        raise Problem(402, "limit_reached", f"This plan allows {ent.monitors} monitors.")

    target = await _target(db, who, body.target_id)
    if target.kind is not TargetKind.REMOTE_HTTP:
        raise Problem(
            422,
            "invalid_target",
            "Only remote HTTP targets can be monitored. An uploaded inventory is re-checked "
            "when your CI uploads it again.",
        )
    monitor = Monitor(
        org_id=who.org_id,
        target_id=target.id,
        enabled=body.enabled,
        notify_email=body.notify_email,
        notify_webhook=body.notify_webhook,
        cron=f"every {ent.monitor_min_interval_minutes}m",
    )
    db.add(monitor)
    await db.flush()
    return MonitorOut.model_validate(monitor)


@router.get("/monitors", response_model=Page[MonitorOut])
async def list_monitors(
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
    limit: int = Query(default=50, ge=1, le=100),
) -> Page[MonitorOut]:
    rows = list(
        (
            await db.execute(
                scoped(select(Monitor), Monitor, who.org_id).order_by(Monitor.id.desc()).limit(limit)
            )
        ).scalars()
    )
    return Page(items=[MonitorOut.model_validate(r) for r in rows])


@router.patch("/monitors/{monitor_id}", response_model=MonitorOut)
async def update_monitor(
    monitor_id: UUID,
    body: MonitorCreate,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> MonitorOut:
    who.require(Role.OWNER, Role.ADMIN)
    monitor = await _monitor(db, who, monitor_id)
    monitor.enabled = body.enabled
    monitor.notify_email = body.notify_email
    monitor.notify_webhook = body.notify_webhook
    if body.enabled:
        monitor.paused_reason = None
    return MonitorOut.model_validate(monitor)


@router.delete("/monitors/{monitor_id}", status_code=204)
async def delete_monitor(
    monitor_id: UUID,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> Response:
    who.require(Role.OWNER, Role.ADMIN)
    await db.delete(await _monitor(db, who, monitor_id))
    return Response(status_code=204)


@router.get("/monitors/{monitor_id}/changes", response_model=Page[ChangeOut])
async def monitor_changes(
    monitor_id: UUID,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
    limit: int = Query(default=25, ge=1, le=100),
) -> Page[ChangeOut]:
    await _monitor(db, who, monitor_id)
    rows = list(
        (
            await db.execute(
                scoped(select(InventoryChange), InventoryChange, who.org_id)
                .where(InventoryChange.monitor_id == monitor_id)
                .order_by(InventoryChange.id.desc())
                .limit(limit)
            )
        ).scalars()
    )
    return Page(items=[ChangeOut.model_validate(r) for r in rows])


async def _target(db: AsyncSession, who: Principal, target_id: UUID) -> Target:
    row = (
        await db.execute(scoped(select(Target), Target, who.org_id).where(Target.id == target_id))
    ).scalar_one_or_none()
    if row is None:
        raise not_found("target")
    return cast("Target", row)


async def _monitor(db: AsyncSession, who: Principal, monitor_id: UUID) -> Monitor:
    row = (
        await db.execute(scoped(select(Monitor), Monitor, who.org_id).where(Monitor.id == monitor_id))
    ).scalar_one_or_none()
    if row is None:
        raise not_found("monitor")
    return cast("Monitor", row)
