"""Creating scans, persisting reports, and the 24-hour result cache.

The pipeline itself is `mcp_audit.audit()` — the CLI's, unchanged. Everything here is
bookkeeping around it: quota, storage, caching, cancellation.
"""

from __future__ import annotations

import secrets as pysecrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from mcp_audit.audit import engine_version
from mcp_audit.models import Inventory, Report
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import insert_ignore
from ..models import InventoryRow, Scan, ScanFinding, ScanStatus

CACHE_WINDOW = timedelta(hours=24)
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


async def cached_scan(
    db: AsyncSession,
    org_id: UUID,
    inventory_id: UUID,
    model: str,
    trials: int,
    task: str | None,
    stub_mode: str,
) -> Scan | None:
    """An identical scan from the last 24 hours, or None.

    Identical means same inventory *content*, model, trials, task, stub mode and engine
    version. A cache hit costs the customer nothing and costs us nothing -- and it is
    the honest answer, because the inputs were the same.
    """
    since = datetime.now(UTC) - CACHE_WINDOW
    found = (
        await db.execute(
            select(Scan)
            .where(
                Scan.org_id == org_id,
                Scan.inventory_id == inventory_id,
                Scan.model == model,
                Scan.trials == trials,
                Scan.stub_mode == stub_mode,
                Scan.status == ScanStatus.SUCCEEDED,
                Scan.created_at >= since,
            )
            .order_by(Scan.created_at.desc())
            .limit(5)
        )
    ).scalars()
    for scan in found:
        if (scan.task or None) != (task or None):
            continue
        report = scan.report or {}
        if report.get("engine_version") == engine_version():
            return scan
    return None


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


async def persist_report(db: AsyncSession, scan: Scan, report: Report) -> None:
    """Store the report and explode its findings into rows for filtering."""
    scan.status = ScanStatus.SUCCEEDED
    scan.verdict = report.verdict.value
    scan.report = truncate_report(report)
    scan.trials = report.trials
    scan.input_tokens = report.usage.input_tokens
    scan.output_tokens = report.usage.output_tokens
    scan.cost_micros = int(report.usage.cost_usd * 1_000_000)
    scan.finished_at = datetime.now(UTC)

    for finding in report.findings:
        if finding.verdict.value == "CLEAN":
            continue  # rows exist for filtering; a clean signal is not a finding
        db.add(
            ScanFinding(
                scan_id=scan.id,
                org_id=scan.org_id,
                tool=finding.signal.tool[:200],
                verdict=finding.verdict.value,
                signal=finding.signal.kind,
                detail=finding.signal.detail[:120],
                real_rate=finding.signal.real_rate,
                san_rate=finding.signal.san_rate,
                p_raw=finding.signal.p_raw,
                p_adj=finding.signal.p_adj,
                evidence=finding.evidence.model_dump(mode="json") if finding.evidence else None,
            )
        )
    await db.flush()


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


def plan_capped_trials(requested: int | None, max_trials: int) -> int:
    from mcp_audit.harness import TRIALS

    return min(requested or TRIALS, max_trials)


def scan_cost_ceiling(plan_ceiling: float) -> float:
    return min(plan_ceiling, settings().scan_cost_ceiling_usd)
