"""Outbound notifications (ROADMAP Phase 6, docs/SECURITY.md §7).

The rule being tested: a notification carries a verdict and a link, and the destination
is a URL a *customer* chose — so it goes through the SSRF guard like any other.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

import pytest

from mcp_audit_cloud.services import notify

SECRET = "whsec-test-secret"


def verify(secret: str, headers: dict[str, str], body: bytes) -> bool:
    """What a receiver would do, using the Standard Webhooks spec."""
    signed = f"{headers['webhook-id']}.{headers['webhook-timestamp']}.".encode() + body
    expected = base64.b64encode(hmac.new(secret.encode(), signed, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(headers["webhook-signature"], f"v1,{expected}")


def stub_transport(monkeypatch, record: list[Any], status: int = 200):
    """Capture what we would have posted, without posting it."""
    import httpx2 as httpx

    async def handle(self, request):
        record.append(request)
        return httpx.Response(status, json={})

    monkeypatch.setattr("httpx2.AsyncHTTPTransport.handle_async_request", handle)
    import ipaddress

    monkeypatch.setattr("mcp_audit_cloud.ssrf.resolve", lambda host: [ipaddress.ip_address("93.184.216.34")])


async def test_a_webhook_is_signed_so_a_receiver_can_verify_it(monkeypatch):
    sent: list[Any] = []
    stub_transport(monkeypatch, sent)
    ok = await notify.send_webhook(
        "https://hooks.example.com/mcp-audit",
        SECRET,
        "scan.completed",
        {"scan_id": "s1", "verdict": "CONFIRMED"},
    )
    assert ok is True
    request = sent[0]
    body = request.content
    headers = {k.lower(): v for k, v in request.headers.items()}
    assert verify(SECRET, headers, body)
    payload = json.loads(body)
    assert payload["type"] == "scan.completed"
    assert payload["data"]["verdict"] == "CONFIRMED"


async def test_a_webhook_never_carries_traces(monkeypatch):
    """A third party's request log is not where the customer's tool inventory belongs."""
    sent: list[Any] = []
    stub_transport(monkeypatch, sent)
    await notify.send_webhook(
        "https://hooks.example.com/mcp-audit",
        SECRET,
        "scan.completed",
        {"scan_id": "s1", "verdict": "CONFIRMED", "url": "https://mcpaudit.dev/app/scans/s1"},
    )
    body = sent[0].content.decode()
    assert "traces" not in body
    assert "arguments" not in body


async def test_a_private_destination_is_refused(monkeypatch):
    """An outbound webhook is the other way to make us fetch our own metadata service."""
    sent: list[Any] = []
    stub_transport(monkeypatch, sent)
    for url in (
        "http://hooks.example.com/x",  # not https
        "https://127.0.0.1/x",
        "https://169.254.169.254/latest/meta-data/",
        "https://10.0.0.5/x",
    ):
        assert await notify.send_webhook(url, SECRET, "scan.completed", {}) is False
    assert sent == [], "nothing should have been posted at all"


async def test_a_rejecting_receiver_is_retried_then_given_up_on(monkeypatch):
    sent: list[Any] = []
    stub_transport(monkeypatch, sent, status=500)
    monkeypatch.setattr(notify, "_backoff", _no_sleep)
    assert await notify.send_webhook("https://hooks.example.com/x", SECRET, "scan.completed", {}) is False
    assert len(sent) == notify.WEBHOOK_RETRIES


async def test_slack_sends_plain_text_only(monkeypatch):
    """Slack renders links and @mentions; the text we relay came from a hostile server."""
    sent: list[Any] = []
    stub_transport(monkeypatch, sent)
    assert await notify.send_slack("https://hooks.slack.com/services/x", "mcp-audit: CONFIRMED") is True
    payload = json.loads(sent[0].content)
    assert set(payload) == {"text"}
    assert payload["text"] == "mcp-audit: CONFIRMED"


async def test_slack_destination_is_ssrf_checked(monkeypatch):
    sent: list[Any] = []
    stub_transport(monkeypatch, sent)
    assert await notify.send_slack("https://127.0.0.1/hook", "hi") is False
    assert sent == []


async def test_email_is_skipped_rather_than_failing_when_unconfigured():
    """A local run has no Resend key; that should log, not raise."""
    assert await notify.send_email("someone@example.com", "subject", "body") is False


def test_the_change_summary_names_what_moved():
    summary = notify._summarise(
        {
            "instructions_changed": True,
            "tools_added": ["read_file"],
            "prose_changed": [{"tool": "read_note", "before": "a", "after": "b"}],
        }
    )
    assert "instructions changed" in summary
    assert "read_file" in summary
    assert "read_note" in summary


def test_an_empty_diff_still_reads_as_a_sentence():
    assert notify._summarise({}) == "the inventory changed"


def test_email_addresses_are_masked_in_logs():
    assert notify._mask("srijith@example.com").startswith("sr***@")
    assert "srijith" not in notify._mask("srijith@example.com")


async def _no_sleep(_attempt: int) -> None:
    return None


@pytest.mark.parametrize("verdict", ["CLEAN", "INCONCLUSIVE", None])
async def test_nothing_is_sent_for_a_verdict_with_nothing_to_act_on(db, verdict, monkeypatch):
    from mcp_audit_cloud.models import Org, Plan, Scan, ScanStatus

    org = Org(
        name="n",
        slug="n",
        plan=Plan.PRO,
        personal=False,
        webhook_url="https://hooks.example.com/x",
        webhook_secret=SECRET,
    )
    db.add(org)
    await db.flush()
    scan = Scan(org_id=org.id, status=ScanStatus.SUCCEEDED, model="m", trials=5, verdict=verdict)
    db.add(scan)
    await db.commit()

    called: list[str] = []
    monkeypatch.setattr(notify, "send_webhook", _record(called, "webhook"))
    monkeypatch.setattr(notify, "send_email", _record(called, "email"))
    await notify.scan_completed(db, scan)
    assert called == []


def _record(sink: list[str], label: str):
    async def recorder(*_args: Any, **_kwargs: Any) -> bool:
        sink.append(label)
        return True

    return recorder
