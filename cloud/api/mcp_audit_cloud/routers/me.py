"""/v1/me, /v1/orgs, /v1/tokens, /v1/plans — identity, teams and CI credentials."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import Principal, new_token, principal
from ..config import settings
from ..db import scoped, session
from ..errors import Problem, not_found
from ..models import ApiToken, Membership, Org, Plan, Role, User
from ..plans import MAX_FREE_ORGS_PER_USER, entitlements, public_table
from ..ratelimit import token_creation
from ..schemas import (
    MemberInvite,
    MemberOut,
    MeOut,
    NotificationSettings,
    OrgCreate,
    OrgOut,
    Page,
    TokenCreate,
    TokenCreated,
    TokenOut,
    UsageOut,
)
from ..services import quota, retention
from ..ssrf import validate as ssrf_validate

router = APIRouter(prefix="/v1", tags=["account"])


@router.get("/plans")
async def plans() -> list[dict[str, Any]]:
    """Public. The pricing page renders this, so it cannot drift from the code."""
    return public_table()


@router.get("/me", response_model=MeOut)
async def me(
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> MeOut:
    usage = await quota.current(db, who.org_id)
    ent = entitlements(who.plan)
    orgs: list[OrgOut] = []
    if who.user_id:
        rows = (
            await db.execute(
                select(Org, Membership.role).join(Membership).where(Membership.user_id == who.user_id)
            )
        ).all()
        orgs = [
            OrgOut(
                id=org.id,
                name=org.name,
                slug=org.slug,
                plan=str(org.plan),
                personal=org.personal,
                role=str(role),
            )
            for org, role in rows
        ]
    current = next((o for o in orgs if o.id == who.org_id), None)
    return MeOut(
        user_id=who.user_id,
        email=who.email,
        orgs=orgs,
        current_org=current,
        plan=str(who.plan),
        entitlements={
            "scans_per_month": ent.scans_per_month,
            "max_trials": ent.max_trials,
            "remote_targets": ent.remote_targets,
            "monitors": ent.monitors,
            "retention_days": ent.retention_days,
            "api_tokens": ent.api_tokens,
            "seats": ent.seats,
            "custom_task": ent.custom_task,
            "included_model_usd": ent.included_model_usd,
            "max_cost_per_scan_usd": ent.max_cost_usd,
            "features": list(ent.features),
        },
        usage=UsageOut(
            period_start=usage.period_start,
            scans_used=usage.scans_used,
            scans_limit=ent.scans_per_month,
            cost_usd=round((usage.cost_micros or 0) / 1_000_000, 4),
            # The limit that actually binds: dollars of model time, not scan count.
            included_model_usd=ent.included_model_usd,
            model_usd_remaining=round(
                max(0.0, ent.included_model_usd - (usage.cost_micros or 0) / 1_000_000), 4
            ),
        ),
    )


@router.post("/orgs", response_model=OrgOut, status_code=201)
async def create_org(
    body: OrgCreate,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> OrgOut:
    if who.user_id is None:
        raise Problem(403, "forbidden", "An API token cannot create organisations.")

    # Every organisation carries its own free model-time budget, so without a cap here
    # "free per org" means "free per org somebody bothers to create" (SECURITY.md §6).
    free_orgs = (
        await db.execute(
            select(func.count())
            .select_from(Membership)
            .join(Org, Org.id == Membership.org_id)
            .where(Membership.user_id == who.user_id, Org.plan == Plan.FREE)
        )
    ).scalar_one()
    if free_orgs >= MAX_FREE_ORGS_PER_USER:
        raise Problem(
            402,
            "too_many_free_orgs",
            f"An account may own {MAX_FREE_ORGS_PER_USER} free organisations. Upgrade one of "
            "them, or run scans locally with the CLI, which is free and unlimited.",
            upgrade_url=f"{settings().web_base_url}/pricing",
        )
    org = Org(name=body.name, slug=_slug(body.name, who.user_id), personal=False, plan=Plan.FREE)
    db.add(org)
    await db.flush()
    db.add(Membership(org_id=org.id, user_id=who.user_id, role=Role.OWNER))
    await db.flush()
    return OrgOut(id=org.id, name=org.name, slug=org.slug, plan=str(org.plan), personal=False, role="owner")


@router.get("/orgs/{org_id}", response_model=OrgOut)
async def get_org(
    org_id: UUID,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> OrgOut:
    # 404 for an org you are not in: the principal is already fenced to one org, and
    # whether another exists is not the caller's business.
    if org_id != who.org_id:
        raise not_found("organisation")
    org = (await db.execute(select(Org).where(Org.id == org_id))).scalar_one()
    return OrgOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        plan=str(org.plan),
        personal=org.personal,
        role=str(who.role),
    )


@router.patch("/orgs/{org_id}", response_model=OrgOut)
async def update_org(
    org_id: UUID,
    body: OrgCreate,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> OrgOut:
    """Rename an organisation. The slug does not move: links and tokens refer to it."""
    if org_id != who.org_id:
        raise not_found("organisation")
    who.require(Role.OWNER, Role.ADMIN)
    org = (await db.execute(select(Org).where(Org.id == org_id))).scalar_one()
    org.name = body.name
    await db.flush()
    return OrgOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        plan=str(org.plan),
        personal=org.personal,
        role=str(who.role),
    )


@router.get("/orgs/{org_id}/members", response_model=Page[MemberOut])
async def members(
    org_id: UUID,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> Page[MemberOut]:
    if org_id != who.org_id:
        raise not_found("organisation")
    rows = (
        await db.execute(select(User, Membership.role).join(Membership).where(Membership.org_id == org_id))
    ).all()
    return Page(
        items=[MemberOut(user_id=u.id, email=u.email, name=u.name, role=str(role)) for u, role in rows]
    )


@router.post("/orgs/{org_id}/members", response_model=MemberOut, status_code=201)
async def invite_member(
    org_id: UUID,
    body: MemberInvite,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> MemberOut:
    if org_id != who.org_id:
        raise not_found("organisation")
    who.require(Role.OWNER, Role.ADMIN)
    ent = who.entitlements
    seats = (await db.execute(select(func.count()).where(Membership.org_id == org_id))).scalar_one()
    if seats >= ent.seats:
        raise Problem(402, "limit_reached", f"This plan includes {ent.seats} seats.")

    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if user is None:
        # They join properly on their first Clerk sign-in; this row reserves the seat.
        user = User(
            clerk_user_id=f"invite_{hashlib.sha256(body.email.encode()).hexdigest()[:24]}", email=body.email
        )
        db.add(user)
        await db.flush()
    existing = (
        await db.execute(select(Membership).where(Membership.org_id == org_id, Membership.user_id == user.id))
    ).scalar_one_or_none()
    if existing is None:
        db.add(Membership(org_id=org_id, user_id=user.id, role=Role(body.role)))
        await db.flush()
    return MemberOut(user_id=user.id, email=user.email, name=user.name, role=body.role)


@router.delete("/orgs/{org_id}/members/{user_id}", status_code=204)
async def remove_member(
    org_id: UUID,
    user_id: UUID,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> Response:
    if org_id != who.org_id:
        raise not_found("organisation")
    who.require(Role.OWNER, Role.ADMIN)
    membership = (
        await db.execute(select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id))
    ).scalar_one_or_none()
    if membership is None:
        raise not_found("member")
    if membership.role is Role.OWNER:
        owners = (
            await db.execute(
                select(func.count()).where(Membership.org_id == org_id, Membership.role == Role.OWNER)
            )
        ).scalar_one()
        if owners <= 1:
            raise Problem(409, "last_owner", "An organisation must keep at least one owner.")
    await db.delete(membership)
    return Response(status_code=204)


@router.post("/tokens", response_model=TokenCreated, status_code=201)
async def create_token(
    body: TokenCreate,
    request: Request,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> TokenCreated:
    who.require(Role.OWNER, Role.ADMIN)
    await token_creation(str(who.org_id))
    live = (
        await db.execute(
            scoped(select(func.count(ApiToken.id)), ApiToken, who.org_id).where(ApiToken.revoked_at.is_(None))
        )
    ).scalar_one()
    if live >= who.entitlements.api_tokens:
        raise Problem(402, "limit_reached", f"This plan allows {who.entitlements.api_tokens} tokens.")

    raw, prefix, digest = new_token()
    token = ApiToken(
        org_id=who.org_id,
        name=body.name,
        prefix=prefix,
        token_hash=digest,
        scopes=["scan"],
        created_by=who.user_id,
        expires_at=(
            datetime.now(UTC) + timedelta(days=body.expires_in_days) if body.expires_in_days else None
        ),
    )
    db.add(token)
    await db.flush()
    # The only time the full token exists outside the caller's hands.
    return TokenCreated(
        id=token.id,
        name=token.name,
        prefix=token.prefix,
        last_used_at=None,
        expires_at=token.expires_at,
        revoked_at=None,
        created_at=token.created_at or datetime.now(UTC),
        token=raw,
    )


@router.get("/tokens", response_model=Page[TokenOut])
async def list_tokens(
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> Page[TokenOut]:
    rows = list(
        (
            await db.execute(scoped(select(ApiToken), ApiToken, who.org_id).order_by(ApiToken.id.desc()))
        ).scalars()
    )
    return Page(items=[TokenOut.model_validate(r) for r in rows])


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(
    token_id: UUID,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> Response:
    who.require(Role.OWNER, Role.ADMIN)
    token = (
        await db.execute(scoped(select(ApiToken), ApiToken, who.org_id).where(ApiToken.id == token_id))
    ).scalar_one_or_none()
    if token is None:
        raise not_found("token")
    # Revocation is immediate: auth checks revoked_at on every request.
    token.revoked_at = datetime.now(UTC)
    return Response(status_code=204)


@router.patch("/orgs/{org_id}/notifications")
async def set_notifications(
    org_id: UUID,
    body: NotificationSettings,
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> dict[str, object]:
    """Outbound webhook and Slack destinations (ROADMAP Phase 6).

    The URLs are validated through the SSRF guard on the way in as well as on every
    send: a customer who can make us POST to 169.254.169.254 has our metadata.
    """
    if org_id != who.org_id:
        raise not_found("organisation")
    who.require(Role.OWNER, Role.ADMIN)
    if "webhooks" not in who.entitlements.features:
        raise Problem(402, "upgrade_required", "Outbound webhooks are a Pro feature.")

    org = (await db.execute(select(Org).where(Org.id == org_id))).scalar_one()
    for url in (body.webhook_url, body.slack_webhook_url):
        if url:
            ssrf_validate(url)
    org.webhook_url = body.webhook_url
    org.slack_webhook_url = body.slack_webhook_url
    if body.webhook_url and not org.webhook_secret:
        # Generated once, shown once: the receiver needs it to verify our signature.
        org.webhook_secret = secrets.token_urlsafe(32)[:64]
    fresh = org.webhook_secret if body.rotate_secret or body.webhook_url else None
    if body.rotate_secret:
        fresh = org.webhook_secret = secrets.token_urlsafe(32)[:64]
    await db.flush()
    return {
        "webhook_url": org.webhook_url,
        "slack_webhook_url": org.slack_webhook_url,
        "webhook_secret": fresh,
    }


@router.delete("/me", status_code=204)
async def delete_account(
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> Response:
    """DPDP/GDPR deletion. Org data goes if this user is the sole owner."""
    if who.user_id is None:
        raise Problem(403, "forbidden", "An API token cannot delete an account.")
    memberships = (
        (await db.execute(select(Membership).where(Membership.user_id == who.user_id))).scalars().all()
    )
    for membership in memberships:
        others = (
            await db.execute(select(func.count()).where(Membership.org_id == membership.org_id))
        ).scalar_one()
        await db.delete(membership)
        if others <= 1:
            await retention.delete_org_data(db, membership.org_id)
            org = (await db.execute(select(Org).where(Org.id == membership.org_id))).scalar_one_or_none()
            if org is not None:
                await db.delete(org)
    user = (await db.execute(select(User).where(User.id == who.user_id))).scalar_one_or_none()
    if user is not None:
        await db.delete(user)
    return Response(status_code=204)


def _slug(name: str, user_id: UUID) -> str:
    base = "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")[:40] or "org"
    return f"{base}-{hashlib.sha256(f'{name}{user_id}'.encode()).hexdigest()[:6]}"
