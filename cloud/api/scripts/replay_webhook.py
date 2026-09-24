"""Replay a recorded billing webhook against a running API (ROADMAP §5.2, Gate 5).

Billing is the one subsystem you cannot test by clicking around: the provider's sandbox
sends events on its own schedule, and the interesting cases (a stale replay, an
out-of-order cancel, a forged signature) are ones it will never send you on purpose.

    # record what the provider actually sent, once, from their dashboard or your logs
    uv run python scripts/replay_webhook.py fixtures/subscription.active.json --org <uuid>

    # the whole lifecycle in order, against a local API
    uv run python scripts/replay_webhook.py --lifecycle --org <uuid>

    # the abuse cases: each must be refused
    uv run python scripts/replay_webhook.py --lifecycle --org <uuid> --forge
    uv run python scripts/replay_webhook.py --lifecycle --org <uuid> --stale
    uv run python scripts/replay_webhook.py --lifecycle --org <uuid> --replay

Signs with BILLING_WEBHOOK_SECRET from the environment, so it exercises the real
verification path rather than a bypass.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2 as httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_audit_cloud.config import settings

#: The lifecycle Gate 5 asks for, in the order a real customer produces it.
LIFECYCLE = [
    ("subscription.active", "active", 0),
    ("subscription.renewed", "active", 30),
    ("subscription.failed", "failed", 60),
    ("subscription.cancelled", "cancelled", 67),
]


def event(kind: str, status: str, day_offset: int, org_id: str, product: str) -> dict[str, Any]:
    at = datetime.now(UTC) + timedelta(days=day_offset)
    return {
        "type": kind,
        "timestamp": at.isoformat(),
        "data": {
            "status": status,
            "product_id": product,
            "subscription_id": "sub_replay_1",
            "customer": {"customer_id": "cus_replay_1"},
            "metadata": {"org_id": org_id},
            "next_billing_date": (at + timedelta(days=30)).isoformat(),
            "quantity": 1,
        },
    }


def sign(secret: str, message_id: str, timestamp: int, body: bytes) -> str:
    key = base64.b64decode(secret.split("_", 1)[1]) if secret.startswith("whsec_") else secret.encode()
    signed = f"{message_id}.{timestamp}.".encode() + body
    return "v1," + base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()


def post(
    client: httpx.Client,
    base: str,
    provider: str,
    payload: dict[str, Any],
    secret: str,
    message_id: str,
    *,
    forge: bool = False,
    stale: bool = False,
) -> tuple[int, str]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = int(time.time()) - (3600 if stale else 0)
    signature = sign(
        "whsec_" + base64.b64encode(b"wrong" * 7)[:44].decode() if forge else secret,
        message_id,
        timestamp,
        body,
    )
    response = client.post(
        f"{base}/webhooks/billing/{provider}",
        content=body,
        headers={
            "content-type": "application/json",
            "webhook-id": message_id,
            "webhook-timestamp": str(timestamp),
            "webhook-signature": signature,
        },
    )
    return response.status_code, response.text[:200]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", nargs="?", type=Path, help="A recorded event body to replay")
    ap.add_argument("--org", required=True, help="org id the event should apply to")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--provider", default=None, help="defaults to the configured provider")
    ap.add_argument("--product", default="prod_pro_m", help="must be in DODO_PRODUCTS")
    ap.add_argument("--lifecycle", action="store_true", help="active -> renewed -> failed -> cancelled")
    ap.add_argument("--forge", action="store_true", help="sign with the wrong key; expect 400")
    ap.add_argument("--stale", action="store_true", help="timestamp an hour old; expect 400")
    ap.add_argument(
        "--replay", action="store_true", help="send each event twice; expect 200 then 200, applied once"
    )
    ap.add_argument(
        "--out-of-order",
        action="store_true",
        help="send cancelled before active; the older event must be ignored",
    )
    args = ap.parse_args()

    cfg = settings()
    provider = args.provider or cfg.billing_provider
    secret = cfg.billing_webhook_secret
    if provider == "none":
        print("BILLING_PROVIDER is 'none': set it to dodo or polar to exercise this path", file=sys.stderr)
        return 2
    if not secret:
        print("BILLING_WEBHOOK_SECRET is empty; signing would be meaningless", file=sys.stderr)
        return 2

    events: list[tuple[str, dict[str, Any]]] = []
    if args.file:
        payload = json.loads(args.file.read_text(encoding="utf-8"))
        payload.setdefault("data", {}).setdefault("metadata", {})["org_id"] = args.org
        events.append((f"msg_file_{int(time.time())}", payload))
    else:
        plan = LIFECYCLE[::-1] if args.out_of_order else LIFECYCLE
        for index, (kind, status, offset) in enumerate(plan):
            events.append(
                (f"msg_{int(time.time())}_{index}", event(kind, status, offset, args.org, args.product))
            )

    failures = 0
    with httpx.Client(timeout=15.0) as client:
        for message_id, payload in events:
            status, text = post(
                client, args.api, provider, payload, secret, message_id, forge=args.forge, stale=args.stale
            )
            expected = 400 if (args.forge or args.stale) else 200
            ok = status == expected
            failures += 0 if ok else 1
            print(f"{payload['type']:28} -> {status} (expected {expected}) {'' if ok else text}")
            if args.replay:
                again, _ = post(client, args.api, provider, payload, secret, message_id)
                # A duplicate must be accepted and ignored, or the provider retries forever.
                print(f"{'  (duplicate)':28} -> {again} (expected 200, applied once)")
                failures += 0 if again == 200 else 1

    print(f"\n{len(events)} events, {failures} unexpected results")
    print(f"Now check the plan: GET {args.api}/v1/billing/subscription with an owner token.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
