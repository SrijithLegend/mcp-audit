"""`scan --cloud`: capture locally, scan on ours.

Capture stays on the user's machine because capturing a stdio server means running it
(CLAUDE.md invariant 3). Only the resulting inventory crosses the wire, and what comes
back is the same `Report` the local engine would have produced.

This is the one place the engine talks to our own service, so it is deliberately small:
POST an inventory, poll, fetch the report. No hidden behaviour, nothing the CLI can do
here that it cannot do offline.
"""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

import httpx2 as httpx

from .credentials import load
from .errors import ApiError, AuditError
from .models import Inventory, Report

DEFAULT_API = "https://api.mcpaudit.dev"
POLL_SECONDS = 2.0
TIMEOUT = 900.0


def api_base() -> str:
    import os

    return os.environ.get("MCP_AUDIT_API", DEFAULT_API).rstrip("/")


def scan_in_cloud(
    inventory: Inventory,
    *,
    task: str | None = None,
    trials: int | None = None,
    model: str | None = None,
    stub_mode: str = "canary",
    token: str | None = None,
    base: str | None = None,
    timeout: float = TIMEOUT,
    progress: Any = None,
) -> Report:
    say = progress or (lambda _: None)
    credential = token or load()
    if not credential:
        raise ApiError("No Cloud token. Run `mcp-audit login --token mcpa_...` first.")

    root = (base or api_base()).rstrip("/")
    body: dict[str, Any] = {"inventory": inventory.model_dump(mode="json"), "stub_mode": stub_mode}
    if task:
        body["task"] = task
    if trials:
        body["trials"] = trials
    if model:
        body["model"] = model

    headers = {
        "authorization": f"Bearer {credential}",
        "content-type": "application/json",
        # A retried submit must not cost a second scan.
        "idempotency-key": uuid4().hex,
    }

    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        created = client.post(f"{root}/v1/scans", json=body, headers=headers)
        if created.status_code >= 400:
            raise _problem(created)
        scan = created.json()
        scan_id = scan["id"]
        say(f"queued as {scan_id} (uses one scan from this period's quota)")

        deadline = time.monotonic() + timeout
        status = scan.get("status", "queued")
        while status in ("queued", "running") and time.monotonic() < deadline:
            time.sleep(POLL_SECONDS)
            polled = client.get(f"{root}/v1/scans/{scan_id}", headers=headers)
            if polled.status_code >= 400:
                raise _problem(polled)
            scan = polled.json()
            # .get, not []: a response that has lost its status should surface as the
            # timeout message below, not as a KeyError traceback.
            if scan.get("status", status) != status:
                status = str(scan["status"])
                say(f"scan is {status}")

        if status in ("queued", "running"):
            raise ApiError(
                f"Scan {scan_id} was still {status} after {timeout:g}s. It may finish; check "
                f"{root}/v1/scans/{scan_id}."
            )
        if status != "succeeded":
            raise AuditError(
                f"Scan {status}: {scan.get('error_code') or 'no code'} — {scan.get('error_detail') or ''}"
            )

        report = client.get(f"{root}/v1/scans/{scan_id}/report.json", headers=headers)
        if report.status_code >= 400:
            raise _problem(report)
        return Report.model_validate(report.json())


def _problem(response: httpx.Response) -> AuditError:
    """Turn problem+json into the one-line error the CLI prints."""
    try:
        body = response.json()
        detail = str(body.get("detail") or body)
        upgrade = body.get("upgrade_url")
    except (ValueError, json.JSONDecodeError):
        detail = response.text[:200] or f"HTTP {response.status_code}"
        upgrade = None

    if response.status_code in (401, 403):
        return ApiError(f"{detail} Run `mcp-audit login --token mcpa_...` to refresh the token.")
    if response.status_code == 402:
        return ApiError(f"{detail}{f' See {upgrade}.' if upgrade else ''} The local scan is free.")
    return ApiError(f"Cloud returned {response.status_code}: {detail}")
