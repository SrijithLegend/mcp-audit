"""Webhooks and the plan state machine (docs/SECURITY.md §7, ROADMAP Gate 5).

The forged-signature and replay tests are the ones that matter: a webhook endpoint that
trusts its body is a free upgrade for anyone who can read our docs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

import pytest

from mcp_audit_cloud.billing import WebhookError
from mcp_audit_cloud.billing.dodo import DodoProvider
from mcp_audit_cloud.billing.polar import PolarProvider
from mcp_audit_cloud.models import Plan, Subscription, SubscriptionStatus
from mcp_audit_cloud.plans import PLANS, listed_plans
from mcp_audit_cloud.routers.billing import GRACE, effective_plan

SECRET = "whsec_" + base64.b64encode(b"k" * 32).decode()


def signed(
    body: dict, secret: str = SECRET, message_id: str = "msg_1", at: int | None = None
) -> tuple[dict, bytes]:
    raw = json.dumps(body).encode()
    timestamp = at if at is not None else int(time.time())
    key = base64.b64decode(secret.split("_", 1)[1])
    signature = base64.b64encode(
        hmac.new(key, f"{message_id}.{timestamp}.".encode() + raw, hashlib.sha256).digest()
    ).decode()
    headers = {
        "webhook-id": message_id,
        "webhook-timestamp": str(timestamp),
        "webhook-signature": f"v1,{signature}",
    }
    return headers, raw


def provider(monkeypatch) -> DodoProvider:
    monkeypatch.setenv("DODO_PRODUCTS", "pro_month:prod_pro_m,team_month:prod_team_m")
    from mcp_audit_cloud.billing import dodo

    dodo.PLAN_BY_PRODUCT.clear()
    return DodoProvider(api_key="k", webhook_secret=SECRET, live=False)


def event_body(status: str = "active", org: str = "11111111-1111-1111-1111-111111111111") -> dict:
    return {
        "type": "subscription.active",
        "timestamp": "2026-09-24T10:00:00Z",
        "data": {
            "status": status,
            "product_id": "prod_pro_m",
            "subscription_id": "sub_1",
            "customer": {"customer_id": "cus_1"},
            "metadata": {"org_id": org},
            "next_billing_date": "2026-10-24T10:00:00Z",
        },
    }


def test_a_valid_signature_is_accepted(monkeypatch):
    impl = provider(monkeypatch)
    headers, raw = signed(event_body())
    event = impl.verify_webhook(headers, raw)
    assert event.type == "subscription.active"
    assert event.org_id == "11111111-1111-1111-1111-111111111111"


def test_a_forged_signature_is_refused(monkeypatch):
    impl = provider(monkeypatch)
    headers, raw = signed(event_body(), secret="whsec_" + base64.b64encode(b"x" * 32).decode())
    with pytest.raises(WebhookError, match="signature mismatch"):
        impl.verify_webhook(headers, raw)


def test_a_tampered_body_is_refused(monkeypatch):
    impl = provider(monkeypatch)
    headers, raw = signed(event_body())
    tampered = raw.replace(b'"active"', b'"cancelled"')
    with pytest.raises(WebhookError):
        impl.verify_webhook(headers, tampered)


def test_a_stale_timestamp_is_refused(monkeypatch):
    """Replaying last week's subscription.active must not resurrect a plan."""
    impl = provider(monkeypatch)
    headers, raw = signed(event_body(), at=int(time.time()) - 3600)
    with pytest.raises(WebhookError, match="tolerance"):
        impl.verify_webhook(headers, raw)


def test_missing_headers_are_refused(monkeypatch):
    impl = provider(monkeypatch)
    with pytest.raises(WebhookError, match="missing"):
        impl.verify_webhook({}, b"{}")


def test_a_valid_signature_over_non_json_is_refused(monkeypatch):
    impl = provider(monkeypatch)
    raw = b"not json"
    timestamp = int(time.time())
    key = base64.b64decode(SECRET.split("_", 1)[1])
    signature = base64.b64encode(
        hmac.new(key, f"msg_1.{timestamp}.".encode() + raw, hashlib.sha256).digest()
    ).decode()
    with pytest.raises(WebhookError, match="not JSON"):
        impl.verify_webhook(
            {
                "webhook-id": "msg_1",
                "webhook-timestamp": str(timestamp),
                "webhook-signature": f"v1,{signature}",
            },
            raw,
        )


def test_state_mapping(monkeypatch):
    impl = provider(monkeypatch)
    headers, raw = signed(event_body())
    state = impl.to_subscription_state(impl.verify_webhook(headers, raw))
    assert state is not None
    assert state.plan is Plan.PRO
    assert state.status is SubscriptionStatus.ACTIVE
    assert state.customer_id == "cus_1"
    assert state.current_period_end is not None


def test_an_unknown_status_is_never_treated_as_active(monkeypatch):
    """Guessing 'active' on a status we do not recognise gives away the product."""
    impl = provider(monkeypatch)
    headers, raw = signed(event_body(status="something_new"))
    state = impl.to_subscription_state(impl.verify_webhook(headers, raw))
    assert state is not None
    assert state.status is SubscriptionStatus.INCOMPLETE


def test_an_unknown_product_does_not_grant_a_paid_plan(monkeypatch):
    impl = provider(monkeypatch)
    body = event_body()
    body["data"]["product_id"] = "prod_not_ours"
    headers, raw = signed(body)
    state = impl.to_subscription_state(impl.verify_webhook(headers, raw))
    assert state is not None and state.plan is Plan.FREE


def test_an_event_without_an_org_is_ignored(monkeypatch):
    impl = provider(monkeypatch)
    body = event_body()
    body["data"]["metadata"] = {}
    headers, raw = signed(body)
    assert impl.to_subscription_state(impl.verify_webhook(headers, raw)) is None


def test_polar_uses_the_same_verification(monkeypatch):
    monkeypatch.setenv("POLAR_PRODUCTS", "pro_month:polar_pro_m")
    impl = PolarProvider(api_key="k", webhook_secret=SECRET, live=False)
    body = {
        "type": "subscription.created",
        "data": {
            "status": "active",
            "id": "sub_9",
            "customer_id": "cus_9",
            "metadata": {"org_id": "11111111-1111-1111-1111-111111111111", "plan": "pro"},
        },
    }
    headers, raw = signed(body)
    state = impl.to_subscription_state(impl.verify_webhook(headers, raw))
    assert state is not None and state.plan is Plan.PRO and state.status is SubscriptionStatus.ACTIVE


# --- the plan state machine ------------------------------------------------------


def sub(status: SubscriptionStatus, plan: Plan = Plan.PRO, end_offset_days: float = 10) -> Subscription:
    return Subscription(
        org_id=None,
        provider="dodo",
        plan=plan,
        status=status,
        current_period_end=datetime.now(UTC) + timedelta(days=end_offset_days),
        state_at=datetime.now(UTC),
    )


def test_active_keeps_its_plan():
    assert effective_plan(sub(SubscriptionStatus.ACTIVE)) is Plan.PRO


def test_past_due_keeps_features_during_the_grace_period():
    """A failed card is usually an expired card. Locking a security tool mid-incident
    over one is hostile."""
    assert effective_plan(sub(SubscriptionStatus.PAST_DUE, end_offset_days=-1)) is Plan.PRO


def test_past_due_falls_back_to_free_after_the_grace_period():
    row = sub(SubscriptionStatus.PAST_DUE, end_offset_days=-(GRACE.days + 2))
    assert effective_plan(row) is Plan.FREE


def test_cancelled_keeps_the_plan_until_the_period_they_paid_for_ends():
    assert effective_plan(sub(SubscriptionStatus.CANCELED, end_offset_days=5)) is Plan.PRO
    assert effective_plan(sub(SubscriptionStatus.CANCELED, end_offset_days=-1)) is Plan.FREE


def test_incomplete_is_free():
    assert effective_plan(sub(SubscriptionStatus.INCOMPLETE)) is Plan.FREE


# --- pricing sanity (ROADMAP §5.1) ----------------------------------------------
#
# There is no margin arithmetic to check any more: scans run on the customer's key, so the
# $19 buys the software and our variable cost is zero (tests/test_economics.py proves the
# "zero" part by grep). What is left is pinning the shape of what customers were sold.


def test_the_plan_table_keeps_its_shape():
    assert PLANS[Plan.FREE].price_monthly_usd == 0.0
    assert PLANS[Plan.PRO].price_monthly_usd == 19.0
    # Two plans on the page; Team stays in the code for existing rows.
    assert [ent.plan for ent in listed_plans()] == [Plan.FREE, Plan.PRO]
    # Free is the trial: default task only, shallow audits, no monitoring.
    assert PLANS[Plan.FREE].custom_task is False
    assert PLANS[Plan.FREE].monitors == 0
    assert PLANS[Plan.PRO].custom_task is True
    assert PLANS[Plan.PRO].monitors > 0


def test_a_paid_plan_is_paid_for_features_not_for_tokens():
    """The pricing model in one assertion: nothing in an entitlement describes an amount of
    model spend, because the customer pays Anthropic directly."""
    for ent in PLANS.values():
        assert not [name for name in ent.__dataclass_fields__ if "model_usd" in name]
        assert not [name for name in ent.__dataclass_fields__ if "cost" in name]
