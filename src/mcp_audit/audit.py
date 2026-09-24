"""The pipeline: inventory in, report out.

The CLI is a thin shell around this, and so is the Cloud worker -- which is the
point. If the hosted product ran a different pipeline, its verdicts would not be
the CLI's verdicts, and the whole "confirm it yourself" story would be a lie.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import Any

from .cost import EXPECTED_TURNS, dollars, estimate, guard
from .differ import analyse, should_escalate
from .dryrun import StubMode
from .harness import CONCURRENCY, DEFAULT_TASK, MAX_TURNS, MODEL, TRIALS, run_both
from .models import Inventory, Report, Trace, Usage, Verdict
from .sanitizer import sanitize, stripped_diff

Progress = Callable[[str], None]


def engine_version() -> str:
    try:
        return _pkg_version("mcp-audit")
    except PackageNotFoundError:  # running from a source checkout
        return "0.0.0+dev"


async def audit(
    inventory: Inventory,
    *,
    api: Any,
    task: str = DEFAULT_TASK,
    trials: int = TRIALS,
    model: str = MODEL,
    stub_mode: StubMode = "canary",
    concurrency: int = CONCURRENCY,
    max_turns: int = MAX_TURNS,
    max_cost: float = 1.0,
    assume_yes: bool = False,
    interactive: bool = True,
    escalate: bool = True,
    progress: Progress | None = None,
) -> Report:
    say = progress or (lambda _: None)
    clean = sanitize(inventory)

    est = await estimate(inventory, clean, task, trials, model, api=api, turns=EXPECTED_TURNS)
    say(est.line())
    guard(est, max_cost, assume_yes, interactive)

    say(f"running {trials} trials per arm")
    real, san = await run_both(
        inventory,
        clean,
        trials=trials,
        task=task,
        api=api,
        model=model,
        stub_mode=stub_mode,
        concurrency=concurrency,
        max_turns=max_turns,
    )
    verdict, findings, tool_verdicts, notes = analyse(real, san, inventory, stub_mode)
    escalated = False

    if escalate and should_escalate(verdict, trials):
        # Borderline at n=5 is exactly where five more trials pay for themselves.
        # Once only: repeated peeking at a growing sample inflates false positives.
        say(f"borderline at n={trials}; running {trials} more per arm")
        more_real, more_san = await run_both(
            inventory,
            clean,
            trials=trials,
            first_trial=trials,
            task=task,
            api=api,
            model=model,
            stub_mode=stub_mode,
            concurrency=concurrency,
            max_turns=max_turns,
        )
        real, san = real + more_real, san + more_san
        verdict, findings, tool_verdicts, notes = analyse(real, san, inventory, stub_mode)
        escalated = True

    traces = real + san
    usage = _usage(traces, model)
    return Report(
        engine_version=engine_version(),
        target=inventory.source or (inventory.server_name or "inventory"),
        inventory_sha256=inventory.sha256(),
        server_name=inventory.server_name,
        model=model,
        task=task,
        trials=len(real),
        stub_mode=stub_mode,
        escalated=escalated,
        temperature=None,  # the API default; see Report.temperature
        verdict=verdict,
        tool_verdicts=tool_verdicts,
        findings=findings,
        traces=traces,
        usage=usage,
        stripped_diff=stripped_diff(inventory, clean),
        notes=notes,
    )


def _usage(traces: list[Trace], model: str) -> Usage:
    usage = Usage(
        input_tokens=sum(t.input_tokens for t in traces),
        output_tokens=sum(t.output_tokens for t in traces),
        cache_read_tokens=sum(t.cache_read_tokens for t in traces),
        api_calls=sum(t.api_calls for t in traces),
    )
    usage.cost_usd = dollars(usage, model)
    return usage


def exit_code(report: Report, fail_on: str = "confirmed") -> int:
    """0 unless the verdict is one the caller asked to fail on (ROADMAP §1.7)."""
    if report.verdict is Verdict.CONFIRMED:
        return 1
    if fail_on == "suspected" and report.verdict is Verdict.SUSPECTED:
        return 1
    return 0
