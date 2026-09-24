"""/v1/scans — submit, list, fetch, cancel, export, share.

Two things happen in the submit path that cannot be reordered:

1. Quota is reserved under a row lock, in the same transaction as the insert.
2. The job is enqueued only after that transaction commits.

Enqueueing first would let a crash between the two hand out free scans; reserving
without a lock would let 50 concurrent submissions all see room for one more.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from mcp_audit.harness import MODEL
from mcp_audit.models import Report
from mcp_audit.report import to_markdown, to_sarif
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import queue
from ..auth import Principal, principal
from ..config import settings
from ..db import scoped, session
from ..errors import Problem, not_found
from ..models import AuditLog, Scan, ScanStatus, Target, TargetKind
from ..ratelimit import redis as redis_client
from ..ratelimit import scan_creation
from ..schemas import Page, ScanCreate, ScanOut
from ..services import quota, secrets, validate
from ..services import scans as scan_service

router = APIRouter(prefix="/v1/scans", tags=["scans"])

IDEMPOTENCY_TTL = 86400


@router.post("", status_code=202, response_model=ScanOut)
async def create_scan(
    request: Request,
    body: ScanCreate,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
    idempotency_key: str = "",
) -> ScanOut:
    await scan_creation(str(who.org_id))
    key = idempotency_key or request.headers.get("Idempotency-Key", "")
    cache = redis_client()

    if key:
        existing = await cache.get(f"idem:{who.org_id}:{key}")
        if existing:
            # A retried POST must not cost a second scan.
            scan = (await db.execute(select(Scan).where(Scan.id == UUID(existing)))).scalar_one_or_none()
            if scan is not None:
                return ScanOut.of(scan)

    if bool(body.inventory) == bool(body.target_id):
        raise Problem(422, "invalid_request", "Send exactly one of `inventory` or `target_id`.")

    ent = who.entitlements
    trials = scan_service.plan_capped_trials(body.trials, ent.max_trials)
    task = validate.check_task(body.task, ent.custom_task)
    model = body.model or MODEL

    target: Target | None = None
    inventory_row = None
    if body.target_id:
        target = (
            await db.execute(scoped(select(Target), Target, who.org_id).where(Target.id == body.target_id))
        ).scalar_one_or_none()
        if target is None:
            raise not_found("target")
        if target.kind is not TargetKind.REMOTE_HTTP:
            raise Problem(422, "invalid_target", "That target has no URL to capture from.")
        # Validate the URL now so the user gets the SSRF error immediately, not in a
        # worker log five seconds later.
        from ..ssrf import validate as ssrf_validate

        ssrf_validate(str(target.url))
        task = task or target.task
    else:
        inventory = validate.parse_inventory(body.inventory or {})
        inventory_row = await scan_service.upsert_inventory(db, who.org_id, inventory)
        cached = await scan_service.cached_scan(
            db, who.org_id, inventory_row.id, model, trials, task, body.stub_mode
        )
        if cached is not None:
            # Same inputs, same engine, less than a day old: the honest answer is the
            # one we already have, and it costs the customer nothing.
            return ScanOut.of(cached)

    await quota.check_breaker(cache, ent.max_cost_usd)
    await quota.reserve(db, who.org_id, who.plan)

    scan = Scan(
        org_id=who.org_id,
        target_id=target.id if target else None,
        inventory_id=inventory_row.id if inventory_row else None,
        status=ScanStatus.QUEUED,
        trials=trials,
        model=model,
        task=task,
        stub_mode=body.stub_mode,
        created_by=who.user_id,
        created_via="api" if who.token_id else "web",
        queued_at=datetime.now(UTC),
    )
    db.add(scan)
    db.add(
        AuditLog(
            org_id=who.org_id,
            actor_user_id=who.user_id,
            actor_token_id=who.token_id,
            action="scan.create",
            target=str(scan.id),
            meta={"trials": trials, "model": model},
            ip=_ip(request),
        )
    )
    await db.flush()

    if body.headers:
        await secrets.stash_one_off(cache, scan.id, body.headers)
    if key:
        await cache.set(f"idem:{who.org_id}:{key}", str(scan.id), ex=IDEMPOTENCY_TTL)

    await db.commit()
    await queue.enqueue("run_scan", str(scan.id))
    return ScanOut.of(scan)


@router.get("", response_model=Page[ScanOut])
async def list_scans(
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
    cursor: str | None = None,
    target_id: UUID | None = None,
    verdict: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> Page[ScanOut]:
    statement = scoped(select(Scan), Scan, who.org_id).order_by(Scan.id.desc()).limit(limit + 1)
    if cursor:
        statement = statement.where(Scan.id < _cursor(cursor))
    if target_id:
        statement = statement.where(Scan.target_id == target_id)
    if verdict:
        statement = statement.where(Scan.verdict == verdict.upper())
    rows = list((await db.execute(statement)).scalars())
    extra = rows[limit:]
    return Page(
        items=[ScanOut.of(r) for r in rows[:limit]], next_cursor=str(rows[limit - 1].id) if extra else None
    )


@router.get("/{scan_id}", response_model=ScanOut)
async def get_scan(
    scan_id: UUID,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> ScanOut:
    return ScanOut.of(await _load(db, who, scan_id))


@router.post("/{scan_id}/cancel", response_model=ScanOut)
async def cancel_scan(
    scan_id: UUID,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> ScanOut:
    scan = await _load(db, who, scan_id)
    if scan.status in (ScanStatus.SUCCEEDED, ScanStatus.FAILED, ScanStatus.CANCELED):
        return ScanOut.of(scan)
    scan.cancel_requested = True
    if scan.status is ScanStatus.QUEUED:
        scan.status = ScanStatus.CANCELED
        scan.finished_at = datetime.now(UTC)
        await quota.refund(db, who.org_id)
    return ScanOut.of(scan)


@router.get("/{scan_id}/report.json")
async def report_json(
    scan_id: UUID,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> dict[str, Any]:
    return _report(await _load(db, who, scan_id))


@router.get("/{scan_id}/report.md")
async def report_markdown(
    scan_id: UUID,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> Response:
    report = Report.model_validate(_report(await _load(db, who, scan_id)))
    return Response(to_markdown(report), media_type="text/markdown; charset=utf-8")


@router.get("/{scan_id}/report.sarif")
async def report_sarif(
    scan_id: UUID,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> Response:
    report = Report.model_validate(_report(await _load(db, who, scan_id)))
    return Response(to_sarif(report), media_type="application/sarif+json")


@router.post("/{scan_id}/share")
async def create_share(
    scan_id: UUID,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> dict[str, str]:
    scan = await _load(db, who, scan_id)
    scan.share_token = scan.share_token or scan_service.share_token()
    return {"url": f"{settings().web_base_url}/share/{scan.share_token}", "token": scan.share_token}


@router.delete("/{scan_id}/share", status_code=204)
async def revoke_share(
    scan_id: UUID,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> Response:
    scan = await _load(db, who, scan_id)
    scan.share_token = None
    return Response(status_code=204)


async def _load(db: AsyncSession, who: Principal, scan_id: UUID) -> Scan:
    scan = (
        await db.execute(scoped(select(Scan), Scan, who.org_id).where(Scan.id == scan_id))
    ).scalar_one_or_none()
    if scan is None:
        # 404 and not 403: whether another org has this id is not the caller's business.
        raise not_found("scan")
    return cast("Scan", scan)


def _report(scan: Scan) -> dict[str, Any]:
    if not scan.report:
        raise Problem(409, "not_ready", f"That scan is {scan.status}; there is no report yet.")
    return dict(scan.report)


def _cursor(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise Problem(422, "invalid_cursor", "That cursor is not valid.") from exc


def _ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "")
    return (
        (forwarded.split(",")[0].strip() or None)
        if forwarded
        else (request.client.host if request.client else None)
    )


def _retention_cutoff(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)
