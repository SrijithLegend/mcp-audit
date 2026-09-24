"""/v1/shared/{token} — a public, read-only, redacted report.

Public means public: no auth, so it is rate limited by IP, marked `noindex`, and the
payload is redacted before it leaves (docs/SECURITY.md §5). A share link exists so
somebody can send a maintainer the evidence, not so a competitor can enumerate which
servers a company runs.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import session
from ..errors import not_found
from ..models import Scan
from ..ratelimit import shared_view
from ..services.scans import redact_for_sharing

router = APIRouter(prefix="/v1/shared", tags=["shared"])


@router.get("/{token}")
async def shared_report(
    token: str,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(session)],
) -> dict[str, Any]:
    await shared_view(_ip(request))
    # No org filter here by design -- the token *is* the authorisation, which is why it
    # is 32 random bytes and revocable in one click.
    scan = (await db.execute(select(Scan).where(Scan.share_token == token))).scalar_one_or_none()
    if scan is None or not scan.report:
        raise not_found("shared report")
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "private, max-age=60"
    return {
        "verdict": scan.verdict,
        "created_at": scan.created_at.isoformat(),
        "report": redact_for_sharing(dict(scan.report)),
    }


def _ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
