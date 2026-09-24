"""Billing behind one protocol, so the provider is a configuration choice (D9)."""

from __future__ import annotations

from functools import lru_cache

from ..config import settings
from .base import BillingProvider, Event, NoBilling, SubscriptionState, WebhookError
from .dodo import DodoProvider
from .polar import PolarProvider


@lru_cache
def provider() -> BillingProvider:
    name = settings().billing_provider
    if name == "dodo":
        return DodoProvider()
    if name == "polar":
        return PolarProvider()
    return NoBilling()


__all__ = [
    "BillingProvider",
    "DodoProvider",
    "Event",
    "NoBilling",
    "PolarProvider",
    "SubscriptionState",
    "WebhookError",
    "provider",
]
