"""Storing a report somebody else produced.

This is the hinge of the whole architecture: the scan happened on the user's machine, on
their key, and what arrives here is the finished `Report` the CLI would have printed. We
validate it, store it, explode its findings into rows, and that is the entire job.

Two consequences worth being explicit about:

- **A report is a claim, not a measurement we made.** Anyone with a token can upload JSON
  saying a server is CONFIRMED. We therefore never present an uploaded report as *our*
  verdict: it is attributed to the engine version and the machine that produced it, and a
  share link says so. The integrity story is that the CLI is open source and the report
  carries the inventory hash, so a reader can re-run it.
- **Everything in it is untrusted text.** It already was -- the traces are what a hostile
  server talked a model into -- so nothing changes except that the numbers are untrusted
  too. Hence the shape limits below.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from mcp_audit.models import Report
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import Problem
from ..models import Scan, ScanFinding, ScanStatus
from ..plans import Entitlements
from .scans import truncate_report

#: Traces are the bulk of a report. More than this and somebody is using us as a blob store.
MAX_TRACES = 64
MAX_CALLS_PER_TRACE = 64
MAX_FINDINGS = 500
MIN_TRIALS = 2


#: Every field of `Report` has a default, so `{}` parses into a tidy-looking CLEAN verdict
#: with zero trials. That is not a report, it is an empty object, and storing it would put a
#: fabricated "CLEAN" in somebody's history. So the fields that only a real run can produce
#: are required explicitly.
REQUIRED_FIELDS = ("format", "verdict", "model", "trials", "inventory_sha256")


def parse_report(payload: dict[str, Any]) -> Report:
    missing = [name for name in REQUIRED_FIELDS if not payload.get(name)]
    if missing:
        raise Problem(
            422,
            "invalid_report",
            f"That is not an mcp-audit report: missing {', '.join(missing)}. Produce one with "
            "`mcp-audit scan ... --json`.",
        )
    try:
        report = Report.model_validate(payload)
    except ValueError as exc:
        raise Problem(422, "invalid_report", f"That is not a valid mcp-audit report: {exc}") from exc
    _check_shape(report)
    return report


def _check_shape(report: Report) -> None:
    if report.trials < MIN_TRIALS:
        # One run is noise; the engine itself refuses fewer than two.
        raise Problem(
            422,
            "invalid_report",
            f"A report needs at least {MIN_TRIALS} trials per arm to mean anything; this one "
            f"claims {report.trials}.",
        )
    if len(report.traces) > MAX_TRACES:
        raise Problem(422, "report_too_large", f"More than {MAX_TRACES} traces in one report.")
    if len(report.findings) > MAX_FINDINGS:
        raise Problem(422, "report_too_large", f"More than {MAX_FINDINGS} findings in one report.")
    for trace in report.traces:
        if len(trace.calls) > MAX_CALLS_PER_TRACE:
            raise Problem(422, "report_too_large", f"A trace holds more than {MAX_CALLS_PER_TRACE} calls.")


def check_entitlements(report: Report, ent: Entitlements) -> None:
    """Paid features are checked on the way in, because that is the only place we see them.

    The scan already happened on the user's own key, so this is not about cost -- it is
    about what the free tier includes. A free report with 20 trials is a Pro report.
    """
    if report.trials > ent.max_trials:
        raise Problem(
            402,
            "upgrade_required",
            f"Reports with more than {ent.max_trials} trials per arm are a paid feature. "
            f"This one has {report.trials}. Re-run with --trials {ent.max_trials}, or upgrade.",
        )
    if report.task and not ent.custom_task:
        # From `meta`, not `harness`: this package must not import the agent loop.
        from mcp_audit.meta import DEFAULT_TASK

        if report.task != DEFAULT_TASK:
            raise Problem(
                402,
                "upgrade_required",
                "Reports with a custom task are a paid feature; free reports use the default "
                "task, which keeps them comparable with each other.",
            )


async def store(
    db: AsyncSession,
    org_id: UUID,
    report: Report,
    *,
    target_id: UUID | None,
    inventory_id: UUID | None,
    created_by: UUID | None,
    via: str,
) -> Scan:
    """Persist an uploaded report as a completed scan.

    Status is `succeeded` on arrival: there is nothing to run. `started_at` and `finished_at`
    come from the report so the timeline reflects when the *scan* happened, not when it was
    uploaded -- a CI job that uploads an hour later should not look like an hour-long scan.
    """
    now = datetime.now(UTC)
    ran_at = report.created_at or now
    scan = Scan(
        org_id=org_id,
        target_id=target_id,
        inventory_id=inventory_id,
        status=ScanStatus.SUCCEEDED,
        trials=report.trials,
        model=report.model or "unknown",
        task=report.task or None,
        stub_mode=report.stub_mode,
        verdict=report.verdict.value,
        report=truncate_report(report),
        input_tokens=report.usage.input_tokens,
        output_tokens=report.usage.output_tokens,
        # The customer's spend on their own key, not ours. Shown back to them.
        cost_micros=int(report.usage.cost_usd * 1_000_000),
        created_by=created_by,
        created_via=via,
        queued_at=now,
        started_at=ran_at,
        finished_at=ran_at,
    )
    db.add(scan)
    await db.flush()

    for finding in report.findings:
        if finding.verdict.value == "CLEAN":
            continue  # rows exist for filtering; a clean signal is not a finding
        db.add(
            ScanFinding(
                scan_id=scan.id,
                org_id=org_id,
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
    return scan
