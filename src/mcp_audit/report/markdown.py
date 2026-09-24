"""Markdown report -- for PR comments and for people who read reports in a browser.

Every piece of server- or model-supplied text goes through `_cell`: backticks and
pipes escaped, invisible characters made visible. Server prose is attacker-supplied
(CLAUDE.md invariant 5), and a markdown report is a place where it would otherwise
be rendered.
"""

from __future__ import annotations

from ..models import LIMITS, Report, Verdict
from .terminal import visible

BADGE = {
    Verdict.CONFIRMED: "**STEERING CONFIRMED**",
    Verdict.SUSPECTED: "**Steering suspected**",
    Verdict.CLEAN: "No steering found",
    Verdict.INCONCLUSIVE: "**Inconclusive**",
}


def _cell(text: object) -> str:
    out = visible(str(text))
    return out.replace("\\", "\\\\").replace("`", "\\`").replace("|", "\\|").replace("\n", " ")


def to_markdown(report: Report) -> str:
    lines = [
        "# mcp-audit report",
        "",
        f"- **Verdict:** {BADGE[report.verdict]}",
        f"- **Target:** `{_cell(report.target)}`",
        f"- **Inventory:** `{report.inventory_sha256[:16]}`",
        f"- **Model:** `{_cell(report.model)}` · **Trials per arm:** {report.trials}"
        + (" (escalated)" if report.escalated else ""),
        f"- **Task:** `{_cell(report.task)}`",
        f"- **Cost:** ${report.usage.cost_usd:.4f} over {report.usage.api_calls} API calls",
        "",
    ]
    reported = [f for f in report.findings if f.verdict is not Verdict.CLEAN]
    if reported:
        lines += [
            "## Findings",
            "",
            "| Verdict | Tool | Signal | Real | Sanitized | p (adj) |",
            "|---|---|---|---|---|---|",
        ]
        for f in reported:
            s = f.signal
            detail = f" [{_cell(s.detail)}]" if s.detail else ""
            lines.append(
                f"| {f.verdict.value} | `{_cell(s.tool)}` | {s.kind}{detail}"
                f"{' (away)' if s.direction == 'away' else ''} "
                f"| {s.real_hits}/{s.n_real} | {s.san_hits}/{s.n_san} | {s.p_adj:.4f} |"
            )
        lines += ["", "## Evidence", ""]
        for f in reported:
            ev = f.evidence
            if ev is None or ev.call is None:
                continue
            lines += [
                f"### `{_cell(f.signal.label())}`",
                "",
                "```",
                f"real arm, trial {ev.trial}: {visible(ev.call.name)}({visible(str(ev.call.arguments))})",
                visible(ev.sanitized_summary),
                "```",
                "",
            ]
    else:
        lines += ["No signal cleared the thresholds.", ""]

    if report.notes:
        lines += ["## Notes", ""] + [f"- {_cell(n)}" for n in report.notes] + [""]
    if report.stripped_diff:
        lines += [
            "<details><summary>What sanitization removed</summary>",
            "",
            "```diff",
            visible(report.stripped_diff[:20000]),
            "```",
            "",
            "</details>",
            "",
        ]
    lines += ["## Limits", "", LIMITS[0], ""]
    return "\n".join(lines)
