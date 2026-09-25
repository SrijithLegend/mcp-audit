"""Storing inventories and reports.

The audit itself happened in the user's CLI on their own key; this module is the storage
side of it. `services/ingest.py` handles an incoming report; what is left here is the
inventory table, the report truncation rule and share tokens.
"""

from __future__ import annotations

import secrets as pysecrets
from typing import Any
from uuid import UUID

from mcp_audit.models import Inventory, Report
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import insert_ignore
from ..models import InventoryRow

#: Stored trace arguments are truncated: a report is evidence, not a copy of whatever
#: the model was steered into reading (docs/SECURITY.md §6).
MAX_STORED_ARG = 512


async def upsert_inventory(db: AsyncSession, org_id: UUID, inventory: Inventory) -> InventoryRow:
    """One row per (org, content hash). Re-uploading the same server is free."""
    digest = inventory.sha256()
    await insert_ignore(
        db,
        InventoryRow,
        {
            "org_id": org_id,
            "sha256": digest,
            "content": inventory.model_dump(mode="json"),
            "source": inventory.source[:2048] or None,
            "server_name": inventory.server_name or None,
            "tool_count": len(inventory.tools),
            "captured_at": inventory.captured_at,
        },
        ["org_id", "sha256"],
    )
    row = (
        await db.execute(
            select(InventoryRow).where(InventoryRow.org_id == org_id, InventoryRow.sha256 == digest)
        )
    ).scalar_one()
    return row


def truncate_report(report: Report) -> dict[str, Any]:
    """What we store: the report, with trace arguments clipped."""
    payload = report.model_dump(mode="json")
    for trace in payload.get("traces", []):
        for call in trace.get("calls", []):
            call["arguments"] = _clip(call.get("arguments"))
    return payload


def _clip(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= MAX_STORED_ARG else value[:MAX_STORED_ARG] + "..."
    if isinstance(value, dict):
        return {k: _clip(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip(v) for v in value]
    return value


def share_token() -> str:
    return pysecrets.token_urlsafe(32)


def redact_for_sharing(report: dict[str, Any]) -> dict[str, Any]:
    """A public share link shows the verdict and the evidence, not the customer.

    Dropped: the task (may describe internal systems), the target (names their
    infrastructure), and the stripped-prose diff (can be large and is the server's
    text verbatim). Traces stay, because they are the point.
    """
    shared = dict(report)
    shared["task"] = ""
    shared["target"] = shared.get("server_name") or "(withheld)"
    shared["stripped_diff"] = ""
    return shared
