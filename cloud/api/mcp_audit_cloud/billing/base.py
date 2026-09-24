"""The billing interface. Dodo first, Polar behind the same protocol (D9).

The shape exists because a Merchant-of-Record relationship is the kind of thing you end
up changing: Stripe India is invite-only today, Dodo is the answer today, and neither of
those facts is permanent. Everything above this file talks about plans and
subscriptions, never about a provider.

One rule with no exceptions: **only a verified webhook changes plan state.** The success
redirect is a URL the customer's browser was pointed at; it proves nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from ..models import Plan, SubscriptionStatus


@dataclass
class Event:
    """A normalised provider event."""

    id: str
    type: str
    org_id: str | None
    occurred_at: datetime | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubscriptionState:
    """What the subscription table should say after applying an event."""

    org_id: str
    plan: Plan
    status: SubscriptionStatus
    customer_id: str | None = None
    subscription_id: str | None = None
    interval: str = "month"
    seats: int = 1
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    state_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class WebhookError(Exception):
    """Signature invalid, timestamp stale, or body unparseable. Never retried into
    existence -- the caller returns 400 and we move on."""


@runtime_checkable
class BillingProvider(Protocol):
    name: str

    async def create_checkout(self, org_id: str, email: str | None, plan: Plan, interval: str) -> str: ...

    async def create_portal(self, customer_id: str) -> str: ...

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> Event: ...

    def to_subscription_state(self, event: Event) -> SubscriptionState | None: ...


class NoBilling:
    """Local development and self-hosting: everything is free, nothing is charged."""

    name = "none"

    async def create_checkout(self, org_id: str, email: str | None, plan: Plan, interval: str) -> str:
        return f"/app/settings/billing?simulated={plan.value}&interval={interval}"

    async def create_portal(self, customer_id: str) -> str:
        return "/app/settings/billing"

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> Event:
        raise WebhookError("billing is disabled in this environment")

    def to_subscription_state(self, event: Event) -> SubscriptionState | None:
        return None
