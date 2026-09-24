"""Terminal report. Evidence is the point.

"CONFIRMED" on its own is a claim; the divergent call with its arguments is what a
maintainer can act on. Verdicts are never colour-only -- the word is always there,
because a red cell means nothing in a CI log or to a colour-blind reader.
"""

from __future__ import annotations

import io

from rich.console import Console
from rich.table import Table
from rich.text import Text

from ..models import LIMITS, Finding, Report, Verdict

HEADLINE = {
    Verdict.CONFIRMED: ("STEERING CONFIRMED", "bold white on red"),
    Verdict.SUSPECTED: ("STEERING SUSPECTED", "bold black on yellow"),
    Verdict.CLEAN: ("no steering found", "bold black on green"),
    Verdict.INCONCLUSIVE: ("INCONCLUSIVE", "bold white on blue"),
}
MAX_CALL = 100
#: Characters that hide a payload in plain sight. Showing them is a feature.
INVISIBLE = {
    **{chr(c): f"<U+{c:04X}>" for c in range(0x200B, 0x2010)},
    **{chr(c): f"<U+{c:04X}>" for c in range(0x202A, 0x202F)},
    **{chr(c): f"<U+{c:04X}>" for c in range(0x2066, 0x206A)},
    **{chr(c): f"<U+{c:04X}>" for c in range(0xE0000, 0xE0080)},
}


def visible(text: str) -> str:
    """Make invisible and bidi-override characters printable."""
    return "".join(INVISIBLE.get(ch, ch) for ch in text)


def render(report: Report, console: Console | None = None, width: int | None = None) -> str:
    # Renders into a buffer by default and returns the text: the caller decides where it
    # goes, so `--json` can keep stdout clean.
    out = console or Console(record=True, width=width or 100, file=io.StringIO(), soft_wrap=False)
    out.print(f"mcp-audit {report.engine_version} — {visible(report.target)}")
    out.print(
        f"{report.trials} trials per arm"
        + (" (escalated)" if report.escalated else "")
        + f", model {report.model}, stub {report.stub_mode}, "
        f"inventory {report.inventory_sha256[:12]}"
    )
    headline, style = HEADLINE[report.verdict]
    out.print()
    out.print(Text(f" VERDICT: {headline} ", style=style))
    out.print()

    reported = [f for f in report.findings if f.verdict is not Verdict.CLEAN]
    if reported:
        table = Table(box=None, pad_edge=False, show_edge=False)
        for column in ("verdict", "tool", "signal", "real", "sanitized", "p (adj)"):
            table.add_column(column, overflow="fold")
        for f in reported:
            s = f.signal
            table.add_row(
                f.verdict.value,
                visible(s.tool),
                _signal_name(s.kind, s.detail, s.direction),
                f"{s.real_hits}/{s.n_real}",
                f"{s.san_hits}/{s.n_san}",
                f"{s.p_adj:.4f}" if s.security_relevant else f"{s.p_raw:.4f} raw",
            )
        out.print(table)
        out.print()
        for f in reported:
            _evidence(out, f)
    else:
        out.print("  No signal cleared the thresholds on either arm.")
        out.print()

    if report.notes:
        for note in report.notes:
            out.print(f"note: {note}")
        out.print()
    usage = report.usage
    out.print(
        f"{usage.api_calls} API calls, {usage.input_tokens} in / {usage.output_tokens} out"
        f" ({usage.cache_read_tokens} cached), cost ${usage.cost_usd:.4f}"
    )
    out.print(f"limits: {LIMITS[0]}", style="dim")
    return out.export_text() if console is None else ""


def _signal_name(kind: str, detail: str, direction: str) -> str:
    name = {
        "called": "tool called",
        "called_first": "called first",
        "sensitive": "sensitive argument",
        "canary_flow": "cross-tool data flow",
        "optional_populated": "optional param filled",
    }.get(kind, kind)
    suffix = f" [{visible(detail)}]" if detail else ""
    away = " (steered AWAY)" if direction == "away" else ""
    return name + suffix + away


def _evidence(out: Console, finding: Finding) -> None:
    ev = finding.evidence
    if ev is None or ev.call is None:
        return
    out.print(f"  {visible(finding.signal.label())}", style="bold")
    out.print(f"    real arm, trial {ev.trial}: {visible(_call(ev.call.name, ev.call.arguments))}")
    out.print(f"    {visible(ev.sanitized_summary)}", style="dim")


def _call(name: str, arguments: dict[str, object]) -> str:
    args = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
    text = f"{name}({args})"
    return text if len(text) <= MAX_CALL else text[:MAX_CALL] + "..."
