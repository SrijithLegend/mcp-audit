"""Dodo Payments adapter (D9). Standard Webhooks signatures.

Dodo is a Merchant of Record: they take the payment, handle global tax, and pay us.
That is why the integration is thin -- we do not compute tax, we do not hold cards, and
we do not store an address.

Signature verification follows the Standard Webhooks spec (`webhook-id`,
`webhook-timestamp`, `webhook-signature`), which Dodo implements, so the same code
verifies Polar and anything else that adopted it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx2 as httpx

from ..config import settings
from ..models import Plan, SubscriptionStatus
from .base import Event, SubscriptionState, WebhookError

API = "https://live.dodopayments.com"
TEST_API = "https://test.dodopayments.com"
TOLERANCE_SECONDS = 300

#: Provider status -> ours. Anything unknown is treated as incomplete rather than
#: active: guessing "active" on an unrecognised status is how you give away the product.
STATUS = {
    "active": SubscriptionStatus.ACTIVE,
    "trialing": SubscriptionStatus.ACTIVE,
    "on_hold": SubscriptionStatus.PAST_DUE,
    "past_due": SubscriptionStatus.PAST_DUE,
    "failed": SubscriptionStatus.PAST_DUE,
    "cancelled": SubscriptionStatus.CANCELED,
    "canceled": SubscriptionStatus.CANCELED,
    "expired": SubscriptionStatus.CANCELED,
}

PLAN_BY_PRODUCT: dict[str, tuple[Plan, str]] = {}


def _product_map() -> dict[str, tuple[Plan, str]]:
    """`DODO_PRODUCTS=pro_month:prod_x,pro_year:prod_y,team_month:prod_z`.

    Kept in configuration rather than code because the ids differ between test and live
    mode, and a hardcoded test-mode id in production is a silent free tier.
    """
    if PLAN_BY_PRODUCT:
        return PLAN_BY_PRODUCT
    import os

    for pair in (os.environ.get("DODO_PRODUCTS") or "").split(","):
        if ":" not in pair:
            continue
        label, product = pair.split(":", 1)
        plan_name, _, interval = label.partition("_")
        try:
            PLAN_BY_PRODUCT[product.strip()] = (Plan(plan_name.strip()), interval or "month")
        except ValueError:
            continue
    return PLAN_BY_PRODUCT


class DodoProvider:
    name = "dodo"

    def __init__(
        self, api_key: str | None = None, webhook_secret: str | None = None, live: bool | None = None
    ):
        cfg = settings()
        self.api_key = api_key or cfg.billing_api_key
        self.webhook_secret = webhook_secret or cfg.billing_webhook_secret
        self.base = API if (live if live is not None else cfg.environment == "production") else TEST_API

    async def create_checkout(self, org_id: str, email: str | None, plan: Plan, interval: str) -> str:
        product = next(
            (p for p, (pl, iv) in _product_map().items() if pl is plan and iv == interval),
            None,
        )
        if product is None:
            raise WebhookError(f"no configured product for {plan.value}/{interval}")
        payload: dict[str, Any] = {
            "product_cart": [{"product_id": product, "quantity": 1}],
            "customer": {"email": email} if email else {},
            # The org id rides in metadata and comes back on the webhook. It is the only
            # link between a payment and an account, so it is never inferred from email.
            "metadata": {"org_id": org_id, "plan": plan.value, "interval": interval},
            "return_url": f"{settings().web_base_url}/app/settings/billing?checkout=done",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self.base}/checkouts",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        url = data.get("checkout_url") or data.get("url")
        if not url:
            raise WebhookError("checkout response had no url")
        return str(url)

    async def create_portal(self, customer_id: str) -> str:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self.base}/customers/{customer_id}/customer-portal/session",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            data = response.json()
        return str(data.get("link") or data.get("url") or f"{settings().web_base_url}/app/settings/billing")

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> Event:
        """Verify over the **raw** body, before anything parses it."""
        lower = {k.lower(): v for k, v in headers.items()}
        message_id = lower.get("webhook-id", "")
        timestamp = lower.get("webhook-timestamp", "")
        signature = lower.get("webhook-signature", "")
        if not (message_id and timestamp and signature):
            raise WebhookError("missing Standard Webhooks headers")
        try:
            sent_at = int(timestamp)
        except ValueError as exc:
            raise WebhookError("bad timestamp") from exc
        if abs(time.time() - sent_at) > TOLERANCE_SECONDS:
            # A replay of yesterday's "subscription.active" must not resurrect a plan.
            raise WebhookError("timestamp outside tolerance")

        expected = self._sign(message_id, sent_at, body)
        # The header may carry several space-separated versioned signatures.
        if not any(hmac.compare_digest(expected, candidate) for candidate in signature.split()):
            raise WebhookError("signature mismatch")

        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise WebhookError("body is not JSON") from exc
        data = payload.get("data") or {}
        metadata = data.get("metadata") or payload.get("metadata") or {}
        return Event(
            id=message_id,
            type=str(payload.get("type") or payload.get("event_type") or "unknown"),
            org_id=metadata.get("org_id"),
            occurred_at=_parse_time(payload.get("timestamp") or payload.get("created_at"))
            or datetime.fromtimestamp(sent_at, tz=UTC),
            raw=payload,
        )

    def _sign(self, message_id: str, timestamp: int, body: bytes) -> str:
        secret = self.webhook_secret
        key = base64.b64decode(secret.split("_", 1)[1]) if secret.startswith("whsec_") else secret.encode()
        signed = f"{message_id}.{timestamp}.".encode() + body
        return "v1," + base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()

    def to_subscription_state(self, event: Event) -> SubscriptionState | None:
        if not event.type.startswith("subscription") and not event.type.startswith("payment"):
            return None
        data = event.raw.get("data") or {}
        if not event.org_id:
            return None
        product_id = str(data.get("product_id") or "")
        plan, interval = _product_map().get(product_id, (Plan.FREE, "month"))
        status = STATUS.get(str(data.get("status") or "").lower(), SubscriptionStatus.INCOMPLETE)
        if event.type.endswith(".cancelled") or event.type.endswith(".canceled"):
            status = SubscriptionStatus.CANCELED
        if event.type.endswith(".failed"):
            status = SubscriptionStatus.PAST_DUE
        return SubscriptionState(
            org_id=event.org_id,
            plan=plan,
            status=status,
            customer_id=str((data.get("customer") or {}).get("customer_id") or data.get("customer_id") or "")
            or None,
            subscription_id=str(data.get("subscription_id") or "") or None,
            interval=interval,
            seats=int(data.get("quantity") or 1),
            current_period_end=_parse_time(data.get("next_billing_date") or data.get("current_period_end")),
            cancel_at_period_end=bool(data.get("cancel_at_next_billing_date")),
            state_at=event.occurred_at,
            raw=event.raw,
        )


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
