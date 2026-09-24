"""What this scan will cost, before it runs.

A tool that can quietly spend $40 because a server shipped 200 tools is a tool
people uninstall. So: count the real turn-1 payload with `count_tokens`, multiply
by what we know about the loop, print it, and refuse to exceed `--max-cost`
(CLAUDE.md invariant 7).

The old "tools x trials x 2" formula was wrong for this harness: one trial runs
the whole inventory, so API calls are `2 x trials x turns`, with turns capped at
MAX_TURNS and averaging far less.
"""

from __future__ import annotations

from typing import Any

from .errors import ApiError, BudgetError
from .harness import MAX_TOKENS, MAX_TURNS, MODEL, build_request
from .models import Inventory, Usage

#: USD per million tokens, (input, output). Cached reads bill at 0.1x input.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-fable-5-1": (10.00, 50.00),
}
CACHE_READ_MULTIPLIER = 0.1

#: Turns per trial, measured on the fixtures: the model usually calls a tool, reads
#: the stub, and stops. MAX_TURNS is the ceiling, not the expectation.
EXPECTED_TURNS = 3


def price(model: str) -> tuple[float, float]:
    if model in PRICES:
        return PRICES[model]
    # An unknown model is priced as the most expensive one we know: erring the other
    # way would let a budget guard wave through a $20 scan.
    return max(PRICES.values(), key=lambda p: p[1])


def dollars(usage: Usage, model: str) -> float:
    price_in, price_out = price(model)
    fresh = max(0, usage.input_tokens)
    return (
        fresh * price_in
        + usage.cache_read_tokens * price_in * CACHE_READ_MULTIPLIER
        + usage.output_tokens * price_out
    ) / 1_000_000


class Estimate:
    """What we will do and what it should cost, in one printable object."""

    def __init__(self, api_calls: int, input_tokens: int, model: str) -> None:
        self.api_calls = api_calls
        self.input_tokens = input_tokens
        self.model = model

    @property
    def expected_usd(self) -> float:
        # Each turn resends the transcript, so input grows; 1.5x the turn-1 payload
        # per turn is the shape we measured on the fixtures.
        usage = Usage(
            input_tokens=int(self.input_tokens * 1.5 * self.api_calls),
            output_tokens=self.api_calls * MAX_TOKENS // 4,
        )
        return dollars(usage, self.model)

    @property
    def worst_usd(self) -> float:
        usage = Usage(
            input_tokens=self.input_tokens * 2 * self.api_calls,
            output_tokens=self.api_calls * MAX_TOKENS,
        )
        return dollars(usage, self.model)

    def line(self) -> str:
        return (
            f"~{self.api_calls} API calls, est. ${self.expected_usd:.2f} "
            f"(worst case ${self.worst_usd:.2f}), model {self.model}"
        )


async def estimate(
    real: Inventory,
    sanitized: Inventory,
    task: str,
    trials: int,
    model: str = MODEL,
    api: Any | None = None,
    turns: int = EXPECTED_TURNS,
) -> Estimate:
    """Token-count the turn-1 payload of both arms for real, then extrapolate."""
    calls = 2 * trials * min(turns, MAX_TURNS)
    tokens = 0
    for inventory in (real, sanitized):
        payload, _ = build_request(inventory, task, model)
        tokens = max(tokens, await _count(api, payload, model))
    return Estimate(api_calls=calls, input_tokens=tokens, model=model)


async def _count(api: Any, payload: dict[str, Any], model: str) -> int:
    if api is None:
        return _guess(payload)
    try:
        result = await api.messages.count_tokens(
            model=model,
            system=payload["system"],
            tools=[{k: v for k, v in t.items() if k != "cache_control"} for t in payload["tools"]],
            messages=payload["messages"],
        )
        return int(getattr(result, "input_tokens", 0)) or _guess(payload)
    except Exception as exc:  # counting must never be the thing that fails a scan
        name = type(exc).__name__
        if name in ("AuthenticationError", "PermissionDeniedError"):
            raise ApiError(f"Anthropic rejected the API key ({name}).") from exc
        return _guess(payload)


def _guess(payload: dict[str, Any]) -> int:
    """~4 characters per token. Only used when count_tokens is unavailable."""
    return len(str(payload)) // 4


def guard(est: Estimate, max_cost: float, assume_yes: bool, interactive: bool) -> None:
    """A hard stop, not a warning.

    Non-interactive callers (CI) are never prompted -- they get the refusal, because
    a build that hangs on a y/n is worse than a build that fails.
    """
    if est.worst_usd <= max_cost or assume_yes:
        return
    raise BudgetError(
        f"Estimated worst case ${est.worst_usd:.2f} exceeds --max-cost ${max_cost:.2f}. "
        + ("Re-run with --yes to accept, or lower --trials." if interactive else "Raise --max-cost in CI.")
    )
