"""`scan --push`: run the audit here, keep the report there.

The model is yours. Your key never leaves this machine, and mcp-audit Cloud never holds one
-- it could not run a scan if it wanted to. What crosses the wire is the finished `Report`,
after the audit is done.

So this module is small on purpose: POST a report, get an id back. No polling, no job, no
waiting on somebody else's queue.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx2 as httpx

from .credentials import load
from .errors import ApiError, AuditError
from .models import Inventory, Report

DEFAULT_API = "https://api.mcpaudit.dev"
TIMEOUT = 60.0


def api_base() -> str:
    import os

    return os.environ.get("MCP_AUDIT_API", DEFAULT_API).rstrip("/")


def push_report(
    report: Report,
    *,
    inventory: Inventory | None = None,
    target_id: str | None = None,
    token: str | None = None,
    base: str | None = None,
    timeout: float = TIMEOUT,
    progress: Any = None,
) -> str:
    """Upload a finished report. Returns the URL to look at it.

    `inventory` is optional and worth sending: the report carries only its hash, so uploading
    the inventory too is what lets the Cloud show a rug-pull diff later.
    """
    say = progress or (lambda _: None)
    credential = token or load()
    if not credential:
        raise ApiError("No Cloud token. Run `mcp-audit login --token mcpa_...` first.")

    root = (base or api_base()).rstrip("/")
    body: dict[str, Any] = {"report": report.model_dump(mode="json")}
    if inventory is not None:
        body["inventory"] = inventory.model_dump(mode="json")
    if target_id:
        body["target_id"] = target_id

    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        response = client.post(
            f"{root}/v1/scans",
            json=body,
            headers={
                "authorization": f"Bearer {credential}",
                "content-type": "application/json",
                # A retried upload must not store the report twice.
                "idempotency-key": uuid4().hex,
            },
        )
        if response.status_code >= 400:
            raise _problem(response)
        scan = response.json()

    url = f"{root.replace('api.', 'app.', 1)}/app/scans/{scan.get('id', '')}"
    say(f"pushed {report.verdict.value} to {url}")
    return url


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
        # The scan already ran locally and the report is on disk if they asked for one, so
        # nothing was lost -- say that rather than just refusing.
        return ApiError(
            f"{detail}{f' See {upgrade}.' if upgrade else ''} "
            "The scan itself already ran; only the upload was refused."
        )
    return ApiError(f"Cloud returned {response.status_code}: {detail}")
