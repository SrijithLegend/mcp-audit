"""/v1/billing and the inbound webhook.

The plan state machine (ROADMAP §5.2):

    active -> past_due (7-day grace, features stay on) -> canceled -> Free at period end

Three rules:

- **Only the webhook changes plan state.** The success redirect is a URL the browser was
  pointed at; anybody can visit it.
- **Idempotent.** The event id is a primary key; a duplicate delivery inserts nothing and
  returns 200, so the provider stops retrying.
- **Order-independent.** Providers deliver out of order. An event older than the state we
  already stored is ignored rather than applied.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import Principal, principal
from ..billing import WebhookError, provider
from ..billing.base import SubscriptionState
from ..config import settings
from ..db import insert_ignore, session, set_org
from ..errors import Problem
from ..models import Org, Plan, Role, Subscription, SubscriptionStatus, WebhookEvent
from ..schemas import CheckoutRequest, UrlOut

router = APIRouter(tags=["billing"])
log = structlog.get_logger()

GRACE = timedelta(days=7)
MAX_WEBHOOK_BYTES = 256 * 1024


@router.post("/v1/billing/checkout", response_model=UrlOut)
async def checkout(
    body: CheckoutRequest,
    who: Annotated[Principal, Depends(principal)],
) -> UrlOut:
    who.require(Role.OWNER)
    url = await provider().create_checkout(str(who.org_id), who.email, Plan(body.plan), body.interval)
    return UrlOut(url=url)


@router.post("/v1/billing/portal", response_model=UrlOut)
async def portal(
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> UrlOut:
    who.require(Role.OWNER)
    row = (
        await db.execute(select(Subscription).where(Subscription.org_id == who.org_id))
    ).scalar_one_or_none()
    if row is None or not row.customer_id:
        raise Problem(409, "no_subscription", "This organisation has no billing account yet.")
    return UrlOut(url=await provider().create_portal(row.customer_id))


@router.post("/webhooks/billing/{name}")
async def webhook(
    name: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(session)],
) -> Response:
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        return Response(status_code=413)

    impl = provider()
    if name != impl.name:
        # Wrong endpoint for the configured provider: not an error worth retrying.
        return Response(status_code=200)
    try:
        event = impl.verify_webhook(dict(request.headers), body)
    except WebhookError as exc:
        log.warning("webhook.rejected", provider=name, reason=str(exc))
        # 400, not 200: a forged or stale event should be visible in their dashboard.
        return Response(status_code=400)

    inserted = await insert_ignore(
        db,
        WebhookEvent,
        {"provider": name, "event_id": event.id, "event_type": event.type},
        ["provider", "event_id"],
    )
    if inserted == 0:
        # Already handled. Saying 200 is what makes the provider stop retrying.
        return Response(status_code=200)

    state = impl.to_subscription_state(event)
    if state is not None:
        await apply_state(db, state)
    await db.execute(
        update(WebhookEvent)
        .where(WebhookEvent.provider == name, WebhookEvent.event_id == event.id)
        .values(processed_at=datetime.now(UTC)),
        execution_options={"synchronize_session": False},
    )
    await db.commit()
    log.info("webhook.processed", provider=name, type=event.type, org_id=event.org_id)
    return Response(status_code=200)


async def apply_state(db: AsyncSession, state: SubscriptionState) -> None:
    """Write the subscription and move the org's plan, if this event is the newest."""
    try:
        org_id = UUID(state.org_id)
    except ValueError:
        log.warning("webhook.bad_org", org_id=state.org_id)
        return
    org = (await db.execute(select(Org).where(Org.id == org_id))).scalar_one_or_none()
    if org is None:
        log.warning("webhook.unknown_org", org_id=state.org_id)
        return
    await set_org(db, org_id)

    row = (await db.execute(select(Subscription).where(Subscription.org_id == org_id))).scalar_one_or_none()
    if row is None:
        row = Subscription(org_id=org_id, provider=provider().name, status=state.status, plan=state.plan)
        db.add(row)
    elif row.state_at and state.state_at and state.state_at < row.state_at:
        # Out of order: a "created" arriving after "canceled" must not resurrect it.
        log.info("webhook.stale_event", org_id=state.org_id)
        return

    row.provider = provider().name
    row.customer_id = state.customer_id or row.customer_id
    row.subscription_id = state.subscription_id or row.subscription_id
    row.plan = state.plan
    row.status = state.status
    row.interval = state.interval
    row.seats = state.seats
    row.current_period_end = state.current_period_end
    row.cancel_at_period_end = state.cancel_at_period_end
    row.state_at = state.state_at or datetime.now(UTC)
    row.raw = state.raw

    org.plan = effective_plan(row)
    await db.flush()


def effective_plan(row: Subscription, now: datetime | None = None) -> Plan:
    """What the org is entitled to right now.

    `past_due` keeps its features for a grace period: a failed card is usually an
    expired card, and locking a security tool out mid-incident over one is hostile.
    """
    at = now or datetime.now(UTC)
    if row.status is SubscriptionStatus.ACTIVE:
        return row.plan
    if row.status is SubscriptionStatus.PAST_DUE:
        end: datetime = row.current_period_end or row.state_at or at
        return row.plan if at <= end + GRACE else Plan.FREE
    if row.status is SubscriptionStatus.CANCELED:
        # Paid until the end of the period they paid for. Then Free -- never deleted.
        until = row.current_period_end
        return row.plan if until and at < until else Plan.FREE
    return Plan.FREE


@router.get("/v1/billing/subscription")
async def subscription(
    who: Annotated[Principal, Depends(principal)],
    db: Annotated[AsyncSession, Depends(session)],
) -> dict[str, object]:
    row = (
        await db.execute(select(Subscription).where(Subscription.org_id == who.org_id))
    ).scalar_one_or_none()
    if row is None:
        return {"plan": "free", "status": "none", "provider": provider().name}
    return {
        "plan": str(row.plan),
        "status": str(row.status),
        "provider": row.provider,
        "interval": row.interval,
        "seats": row.seats,
        "current_period_end": row.current_period_end.isoformat() if row.current_period_end else None,
        "cancel_at_period_end": row.cancel_at_period_end,
        "effective_plan": str(effective_plan(row)),
        "manage_url": f"{settings().web_base_url}/app/settings/billing",
    }
