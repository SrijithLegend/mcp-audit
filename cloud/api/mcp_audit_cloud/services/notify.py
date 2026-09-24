"""Telling people something happened: email (Resend) and signed outbound webhooks.

Two rules that are not negotiable:

- A notification carries a verdict and a link, never full traces. The traces are
  attacker-controlled text and the customer's own tool inventory; neither belongs in an
  email body or a third-party webhook endpoint's logs.
- An outbound webhook URL is a URL a *customer* chose, so it goes through the same SSRF
  guard as a scan target (docs/SECURITY.md §7). Our webhook sender must not become the
  thing that reads our metadata service.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from uuid import UUID

import httpx2 as httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import InventoryChange, Membership, Monitor, Scan, User

log = structlog.get_logger()

WEBHOOK_TIMEOUT = 5.0
WEBHOOK_RETRIES = 3


def sign(secret: str, message_id: str, timestamp: int, body: bytes) -> str:
    """Standard Webhooks signature, so receivers can use an off-the-shelf verifier."""
    signed = f"{message_id}.{timestamp}.".encode() + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).digest()
    import base64

    return "v1," + base64.b64encode(digest).decode()


async def send_webhook(url: str, secret: str, event: str, payload: dict[str, Any]) -> bool:
    from ..ssrf import SsrfError, guarded_client

    body = json.dumps({"type": event, "data": payload}, separators=(",", ":")).encode()
    message_id = f"msg_{hashlib.sha256(body).hexdigest()[:24]}"
    timestamp = int(time.time())
    headers = {
        "content-type": "application/json",
        "webhook-id": message_id,
        "webhook-timestamp": str(timestamp),
        "webhook-signature": sign(secret, message_id, timestamp, body),
        "user-agent": "mcp-audit-webhooks/1",
    }
    try:
        client = guarded_client(url, headers=headers)
    except SsrfError as exc:
        log.info("webhook.refused", url=url[:120], reason=str(exc))
        return False
    try:
        for attempt in range(WEBHOOK_RETRIES):
            try:
                response = await client.post(url, content=body)
                if response.status_code < 300:
                    return True
                log.info("webhook.rejected", status=response.status_code, attempt=attempt)
            except httpx.HTTPError as exc:
                log.info("webhook.error", error=str(exc)[:120], attempt=attempt)
            await _backoff(attempt)
        return False
    finally:
        await client.aclose()


async def _backoff(attempt: int) -> None:
    import asyncio

    await asyncio.sleep(min(2**attempt, 8))


async def send_email(to: str, subject: str, text: str) -> bool:
    """Plain text only. Server-supplied strings never become HTML (invariant 5)."""
    cfg = settings()
    if not cfg.resend_api_key:
        log.info("email.skipped", to=_mask(to), subject=subject)
        return False
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {cfg.resend_api_key}"},
            json={"from": cfg.email_from, "to": [to], "subject": subject, "text": text},
        )
    if response.status_code >= 300:
        log.warning("email.failed", status=response.status_code)
        return False
    return True


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:2]}***@{domain}"


async def owners(db: AsyncSession, org_id: UUID) -> list[str]:
    rows = (
        await db.execute(select(User.email).join(Membership).where(Membership.org_id == org_id))
    ).scalars()
    return [e for e in rows if e]


async def org_webhook(db: AsyncSession, org_id: UUID) -> tuple[str | None, str | None, str | None]:
    """(webhook url, signing secret, slack url) for an org, or three Nones."""
    from ..models import Org

    org = (await db.execute(select(Org).where(Org.id == org_id))).scalar_one_or_none()
    if org is None:
        return None, None, None
    return org.webhook_url, org.webhook_secret, org.slack_webhook_url


async def send_slack(url: str, text: str) -> bool:
    """Slack incoming webhook, plain text.

    Plain text because Slack renders links and mentions, and the text we are relaying
    came from a server we are auditing for trying to steer a model (invariant 5).
    """
    from ..ssrf import SsrfError, guarded_client

    try:
        client = guarded_client(url, headers={"content-type": "application/json"})
    except SsrfError as exc:
        log.info("slack.refused", reason=str(exc))
        return False
    try:
        response = await client.post(url, content=json.dumps({"text": text}).encode())
        return response.status_code < 300
    except httpx.HTTPError as exc:
        log.info("slack.error", error=str(exc)[:120])
        return False
    finally:
        await client.aclose()


async def scan_completed(db: AsyncSession, scan: Scan) -> None:
    """Only worth telling anyone when there is something to act on."""
    if scan.verdict not in ("CONFIRMED", "SUSPECTED"):
        return
    link = f"{settings().web_base_url}/app/scans/{scan.id}"
    for email in await owners(db, scan.org_id):
        await send_email(
            email,
            f"mcp-audit: {scan.verdict} on a scanned MCP server",
            f"A scan finished with the verdict {scan.verdict}.\n\n{link}\n\n"
            "The report shows which tool call diverged and what the sanitized run did instead.",
        )

    url, secret, slack = await org_webhook(db, scan.org_id)
    if url and secret:
        # Verdict and link only. The traces are attacker-controlled text and the
        # customer's own tool inventory; neither belongs in a third party's request log.
        await send_webhook(
            url,
            secret,
            "scan.completed",
            {
                "scan_id": str(scan.id),
                "verdict": scan.verdict,
                "trials": scan.trials,
                "model": scan.model,
                "url": link,
            },
        )
    if slack:
        await send_slack(slack, f"mcp-audit: {scan.verdict} — {link}")


async def inventory_changed(db: AsyncSession, monitor: Monitor, change: InventoryChange) -> None:
    """The rug-pull alert. Says what changed and links to the re-scan."""
    link = f"{settings().web_base_url}/app/monitors/{monitor.id}"
    summary = _summarise(change.diff)
    for email in await owners(db, monitor.org_id):
        await send_email(
            email,
            "mcp-audit: a monitored MCP server changed its tool inventory",
            f"{summary}\n\nWe started a scan of the new inventory automatically.\n{link}\n",
        )
    url, secret, slack = await org_webhook(db, monitor.org_id)
    destination = monitor.notify_webhook or url
    if destination and secret:
        await send_webhook(
            destination,
            secret,
            "monitor.changed",
            {
                "monitor_id": str(monitor.id),
                "old_sha256": change.old_sha256,
                "new_sha256": change.new_sha256,
                "scan_id": str(change.scan_id) if change.scan_id else None,
                "summary": summary,
                "url": link,
            },
        )
    if slack:
        await send_slack(slack, f"mcp-audit: a monitored MCP server changed. {summary} — {link}")


def _summarise(diff: dict[str, Any]) -> str:
    parts = []
    if diff.get("instructions_changed"):
        parts.append("the server's instructions changed")
    for key, label in (("tools_added", "added"), ("tools_removed", "removed")):
        names = diff.get(key) or []
        if names:
            parts.append(f"{label} {len(names)} tool(s): {', '.join(names[:5])}")
    if diff.get("prose_changed"):
        tools = [c["tool"] for c in diff["prose_changed"]][:5]
        parts.append(f"rewrote the description of {', '.join(tools)}")
    if diff.get("schema_changed"):
        tools = [c["tool"] for c in diff["schema_changed"]][:5]
        parts.append(f"changed the parameters of {', '.join(tools)}")
    return "; ".join(parts) or "the inventory changed"
