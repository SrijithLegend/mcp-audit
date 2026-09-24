"""Who is calling, and what they are allowed to do.

Two credential types (D8):

- **Clerk session JWT** from the web app. Verified against Clerk's JWKS, with issuer,
  audience/`azp`, expiry and not-before all checked. We never roll our own login.
- **`mcpa_` API token** from CI. 32 random bytes, shown once, stored as sha256, compared
  in constant time, revocable immediately.

`org_id` for authorisation comes from the principal and never from the request body
(docs/SECURITY.md §5).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx2 as httpx
import jwt
from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import session, set_org
from .errors import Problem
from .models import ApiToken, Membership, Org, Plan, Role, User
from .plans import Entitlements, entitlements

TOKEN_PREFIX = "mcpa_"
TOKEN_BYTES = 32
JWKS_TTL = 600.0

_jwks_cache: dict[str, Any] = {"at": 0.0, "keys": None}


@dataclass
class Principal:
    """The authenticated caller, already resolved to one org and one role."""

    org_id: UUID
    role: Role
    plan: Plan
    user_id: UUID | None = None
    token_id: UUID | None = None
    email: str | None = None

    @property
    def entitlements(self) -> Entitlements:
        return entitlements(self.plan)

    def require(self, *roles: Role) -> None:
        if self.role not in roles:
            raise Problem(403, "forbidden", f"This action needs one of: {', '.join(roles)}.")


def new_token() -> tuple[str, str, str]:
    """(token shown once, prefix for display, sha256 for storage)."""
    raw = TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)
    return raw, raw[: len(TOKEN_PREFIX) + 6], hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _jwks() -> dict[str, Any]:
    """Clerk's public keys, cached and refreshed. Rotation must not need a deploy."""
    now = time.monotonic()
    if _jwks_cache["keys"] is not None and now - _jwks_cache["at"] < JWKS_TTL:
        return dict(_jwks_cache["keys"])
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(settings().clerk_jwks_url)
        response.raise_for_status()
        keys = response.json()
    _jwks_cache.update(at=now, keys=keys)
    return dict(keys)


async def verify_clerk_jwt(token: str) -> dict[str, Any]:
    cfg = settings()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise Problem(401, "invalid_token", "That session token is malformed.") from exc
    if header.get("alg") not in ("RS256", "RS512", "ES256"):
        # `none`, or a symmetric alg we would verify with a public key, is an attack.
        raise Problem(401, "invalid_token", "Unsupported token algorithm.")

    keys = await _jwks()
    key = next((k for k in keys.get("keys", []) if k.get("kid") == header.get("kid")), None)
    if key is None:
        raise Problem(401, "invalid_token", "Unknown signing key.")
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key=jwt.PyJWK.from_dict(key).key,
            algorithms=[header["alg"]],
            issuer=cfg.clerk_issuer or None,
            options={"require": ["exp", "iat", "sub"], "verify_aud": False},
            leeway=30,
        )
    except jwt.PyJWTError as exc:
        raise Problem(401, "invalid_token", "That session token is not valid.") from exc

    parties = cfg.clerk_authorized_parties
    if parties and claims.get("azp") not in parties:
        # A token minted for another site must not work here.
        raise Problem(401, "invalid_token", "Token was issued for a different application.")
    return claims


async def upsert_user(db: AsyncSession, claims: dict[str, Any]) -> tuple[User, Org, Role]:
    """First sight of a user creates them and their personal org.

    Nobody should have to create an organisation before they can run one scan.
    """
    clerk_id = str(claims["sub"])
    email = str(claims.get("email") or claims.get("primary_email_address") or f"{clerk_id}@users.noreply")
    name = claims.get("name") or claims.get("full_name")

    user = (await db.execute(select(User).where(User.clerk_user_id == clerk_id))).scalar_one_or_none()
    if user is None:
        user = User(clerk_user_id=clerk_id, email=email, name=name)
        db.add(user)
        await db.flush()
    elif user.email != email:
        user.email = email

    membership = (
        await db.execute(
            select(Membership).join(Org).where(Membership.user_id == user.id, Org.personal.is_(True))
        )
    ).scalar_one_or_none()
    if membership is None:
        org = Org(name=name or email.split("@")[0], slug=_slug(clerk_id), personal=True, plan=Plan.FREE)
        db.add(org)
        await db.flush()
        membership = Membership(org_id=org.id, user_id=user.id, role=Role.OWNER)
        db.add(membership)
        await db.flush()
    else:
        org = membership.org
    return user, org, membership.role


def _slug(clerk_id: str) -> str:
    return "u-" + hashlib.sha256(clerk_id.encode()).hexdigest()[:12]


async def _from_api_token(db: AsyncSession, raw: str) -> Principal:
    digest = hash_token(raw)
    row = (await db.execute(select(ApiToken).where(ApiToken.token_hash == digest))).scalar_one_or_none()
    # Constant-time compare even though we looked up by hash: the lookup proves nothing
    # about timing on the caller's side, and this costs nothing.
    if row is None or not hmac.compare_digest(row.token_hash, digest):
        raise Problem(401, "invalid_token", "That API token is not valid.")
    if row.revoked_at is not None:
        raise Problem(401, "revoked_token", "That API token was revoked.")
    if row.expires_at is not None and row.expires_at < datetime.now(UTC):
        raise Problem(401, "expired_token", "That API token has expired.")
    org = (await db.execute(select(Org).where(Org.id == row.org_id))).scalar_one()
    row.last_used_at = datetime.now(UTC)
    # CI tokens act as a member: they can scan, they cannot change billing or seats.
    return Principal(org_id=org.id, role=Role.MEMBER, plan=org.plan, token_id=row.id)


async def _dev_principal(db: AsyncSession, email: str) -> Principal:
    """`Authorization: Bearer dev:<email>` -- local only, refused elsewhere by config."""
    claims = {"sub": f"dev_{email}", "email": email, "name": email.split("@")[0]}
    user, org, role = await upsert_user(db, claims)
    return Principal(org_id=org.id, role=role, plan=org.plan, user_id=user.id, email=user.email)


async def principal(
    request: Request,
    authorization: str = Header(default=""),
    db: AsyncSession = Depends(session),
) -> Principal:
    """The dependency every authenticated route uses."""
    scheme, _, credential = authorization.partition(" ")
    if scheme.lower() != "bearer" or not credential:
        raise Problem(401, "unauthenticated", "Send an Authorization: Bearer token.")

    if credential.startswith(TOKEN_PREFIX):
        found = await _from_api_token(db, credential)
    elif credential.startswith("dev:") and settings().dev_auth_bypass:
        found = await _dev_principal(db, credential[4:])
    else:
        claims = await verify_clerk_jwt(credential)
        user, org, role = await upsert_user(db, claims)
        requested = request.headers.get("X-Org-Id")
        if requested and str(org.id) != requested:
            org, role = await _switch_org(db, user, requested)
        found = Principal(org_id=org.id, role=role, plan=org.plan, user_id=user.id, email=user.email)

    # RLS: everything this transaction touches is now fenced to the principal's org.
    await set_org(db, found.org_id)
    request.state.principal = found
    return found


async def _switch_org(db: AsyncSession, user: User, org_id: str) -> tuple[Org, Role]:
    """Acting in another org requires a membership in it. 404, not 403: an org you are
    not in should not be distinguishable from one that does not exist."""
    try:
        wanted = UUID(org_id)
    except ValueError as exc:
        raise Problem(404, "not_found", "No such organisation.") from exc
    membership = (
        await db.execute(select(Membership).where(Membership.user_id == user.id, Membership.org_id == wanted))
    ).scalar_one_or_none()
    if membership is None:
        raise Problem(404, "not_found", "No such organisation.")
    return membership.org, membership.role


async def optional_principal(
    request: Request,
    authorization: str = Header(default=""),
    db: AsyncSession = Depends(session),
) -> Principal | None:
    """For routes that work signed-out (shared reports) but want the org when present."""
    if not authorization:
        return None
    try:
        return await principal(request, authorization, db)
    except Problem:
        return None
