"""Polar adapter -- the fallback MoR, same protocol, same tests (D9).

Polar also implements Standard Webhooks, so the verification is Dodo's with a different
payload shape on top. Keeping it real (rather than a stub that raises) is the point: if
Dodo ever has to be swapped out, that should be a config change made in an afternoon,
not a migration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx2 as httpx

from ..config import settings
from ..models import Plan, SubscriptionStatus
from .base import Event, SubscriptionState, WebhookError
from .dodo import DodoProvider, _parse_time

API = "https://api.polar.sh/v1"

STATUS = {
    "active": SubscriptionStatus.ACTIVE,
    "trialing": SubscriptionStatus.ACTIVE,
    "past_due": SubscriptionStatus.PAST_DUE,
    "unpaid": SubscriptionStatus.PAST_DUE,
    "canceled": SubscriptionStatus.CANCELED,
    "incomplete": SubscriptionStatus.INCOMPLETE,
    "incomplete_expired": SubscriptionStatus.CANCELED,
}


class PolarProvider(DodoProvider):
    name = "polar"

    async def create_checkout(self, org_id: str, email: str | None, plan: Plan, interval: str) -> str:
        import os

        products = dict(
            pair.split(":", 1) for pair in (os.environ.get("POLAR_PRODUCTS") or "").split(",") if ":" in pair
        )
        product = products.get(f"{plan.value}_{interval}")
        if not product:
            raise WebhookError(f"no configured Polar product for {plan.value}/{interval}")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{API}/checkouts",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "product_id": product,
                    "customer_email": email,
                    "metadata": {"org_id": org_id, "plan": plan.value, "interval": interval},
                    "success_url": f"{settings().web_base_url}/app/settings/billing?checkout=done",
                },
            )
            response.raise_for_status()
        return str(response.json()["url"])

    async def create_portal(self, customer_id: str) -> str:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{API}/customer-sessions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"customer_id": customer_id},
            )
            response.raise_for_status()
        return str(response.json().get("customer_portal_url"))

    def to_subscription_state(self, event: Event) -> SubscriptionState | None:
        if not event.type.startswith("subscription"):
            return None
        data: dict[str, Any] = event.raw.get("data") or {}
        metadata = data.get("metadata") or {}
        org_id = event.org_id or metadata.get("org_id")
        if not org_id:
            return None
        plan_name = str(metadata.get("plan") or "free")
        try:
            plan = Plan(plan_name)
        except ValueError:
            plan = Plan.FREE
        return SubscriptionState(
            org_id=str(org_id),
            plan=plan,
            status=STATUS.get(str(data.get("status") or "").lower(), SubscriptionStatus.INCOMPLETE),
            customer_id=str(data.get("customer_id") or "") or None,
            subscription_id=str(data.get("id") or "") or None,
            interval=str(metadata.get("interval") or "month"),
            seats=int(data.get("seats") or 1),
            current_period_end=_parse_time(data.get("current_period_end")),
            cancel_at_period_end=bool(data.get("cancel_at_period_end")),
            state_at=event.occurred_at or datetime.now(),
            raw=event.raw,
        )
