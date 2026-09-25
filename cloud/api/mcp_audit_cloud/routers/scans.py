"""/v1/scans — upload a report, list them, fetch, export, share.

There is no "run a scan" endpoint, and that is the architecture rather than a gap. Scanning
needs a model; the model is the user's, on their key, on their machine. So the flow is:

    mcp-audit scan <server> --push        # runs locally, uploads the finished report

which means this service never calls an LLM and our inference bill is structurally zero —
`tests/test_invariants.py` greps this directory to prove it. The Cloud's job is what a local
CLI cannot do: keep history, diff it over time, watch for rug pulls, share a result, and let
a team see all of it.

Reports arrive already complete, so the only things that happen here are: check the plan
allows this report, count it against an anti-abuse limit, validate its shape, store it.
"""

from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from mcp_audit.models import Report
from mcp_audit.report import to_markdown, to_sarif
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import Principal, principal
from ..config import settings
from ..db import scoped, session
from ..errors import Problem, not_found
from ..models import AuditLog, Scan, Target
from ..ratelimit import redis as redis_client
from ..ratelimit import scan_creation
from ..schemas import Page, ReportUpload, ScanOut
from ..services import ingest, quota, validate
from ..services import scans as scan_service

router = APIRouter(prefix="/v1/scans", tags=["scans"])

IDEMPOTENCY_TTL = 86400


@router.post("", status_code=201, response_model=ScanOut)
async def upload_report(
    request: Request,
    body: ReportUpload,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> ScanOut:
    """Store a report produced by the user's own CLI or CI run."""
    await scan_creation(str(who.org_id))
    key = request.headers.get("Idempotency-Key", "")
    cache = redis_client()

    if key:
        existing = await cache.get(f"idem:{who.org_id}:{key}")
        if existing:
            # A retried upload must not store the report twice.
            scan = (await db.execute(select(Scan).where(Scan.id == UUID(existing)))).scalar_one_or_none()
            if scan is not None:
                return ScanOut.of(scan)

    report = ingest.parse_report(body.report)
    ingest.check_entitlements(report, who.entitlements)

    target: Target | None = None
    if body.target_id:
        target = (
            await db.execute(scoped(select(Target), Target, who.org_id).where(Target.id == body.target_id))
        ).scalar_one_or_none()
        if target is None:
            raise not_found("target")

    # The inventory the report came from, when the uploader sends it. Optional: the report
    # already carries its hash, and that hash is what monitoring compares.
    inventory_row = None
    if body.inventory:
        inventory = validate.parse_inventory(body.inventory)
        if inventory.sha256() != report.inventory_sha256:
            raise Problem(
                422,
                "inventory_mismatch",
                "That inventory does not hash to the one the report was produced from.",
            )
        inventory_row = await scan_service.upsert_inventory(db, who.org_id, inventory)

    await quota.reserve(db, who.org_id, who.plan)
    scan = await ingest.store(
        db,
        who.org_id,
        report,
        target_id=target.id if target else None,
        inventory_id=inventory_row.id if inventory_row else None,
        created_by=who.user_id,
        via="api" if who.token_id else "web",
    )
    # What the *customer* spent on their own key. Shown back to them, never a limit.
    await quota.record_customer_cost(db, who.org_id, scan.cost_micros)
    db.add(
        AuditLog(
            org_id=who.org_id,
            actor_user_id=who.user_id,
            actor_token_id=who.token_id,
            action="report.upload",
            target=str(scan.id),
            meta={"verdict": scan.verdict, "trials": scan.trials, "engine": report.engine_version},
            ip=_ip(request),
        )
    )
    if key:
        await cache.set(f"idem:{who.org_id}:{key}", str(scan.id), ex=IDEMPOTENCY_TTL)
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
        items=[ScanOut.of(r) for r in rows[:limit]],
        next_cursor=str(rows[limit - 1].id) if extra else None,
    )


@router.get("/{scan_id}", response_model=ScanOut)
async def get_scan(
    scan_id: UUID,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> ScanOut:
    return ScanOut.of(await _load(db, who, scan_id))


@router.delete("/{scan_id}", status_code=204)
async def delete_scan(
    scan_id: UUID,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> Response:
    """Uploads are the user's own data; let them take one back.

    The period allowance is not refunded: it bounds what we ingest, not what we keep, and
    refunding it would make the limit trivially resettable.
    """
    await db.delete(await _load(db, who, scan_id))
    return Response(status_code=204)


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
        raise Problem(409, "not_ready", "That scan has no report stored.")
    return dict(scan.report)


def _cursor(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise Problem(422, "invalid_cursor", "That cursor is not valid.") from exc


def _ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.client.host if request.client else None
