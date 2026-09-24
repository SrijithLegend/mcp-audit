"""Typed failures: one readable line and a stable exit code, never a traceback.

A scanner that dies in an ExceptionGroup is a scanner people stop putting in CI.
Every failure path in the engine raises an `AuditError`; `cli.py` catches it,
prints `str(e)`, and exits with `e.exit_code`. Codes are part of the CLI contract
(ROADMAP §1.7) -- changing one breaks somebody's pipeline.
"""

from __future__ import annotations


class AuditError(Exception):
    """Base: a failure we can explain in one line."""

    exit_code = 1


class CaptureError(AuditError):
    """We could not read the server's inventory."""

    exit_code = 3


class ApiError(AuditError):
    """The model API refused us: missing key, bad key, or an outage."""

    exit_code = 4


class BudgetError(AuditError):
    """The estimated spend exceeds --max-cost."""

    exit_code = 5


class InventoryTooLarge(CaptureError):
    """tools/list kept paginating past what any real server needs."""


class UsageError(AuditError):
    """The user asked for something contradictory. Click/Typer's own code."""

    exit_code = 2


MISSING_KEY = (
    "No API key. Set ANTHROPIC_API_KEY (bring your own key) or run `mcp-audit login` to use mcp-audit Cloud."
)


def first_leaf(exc: BaseException) -> BaseException:
    """The innermost first exception of a (possibly nested) ExceptionGroup.

    anyio task groups report transport failures as groups; users should see the
    one sentence that explains the failure, not the tree.
    """
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:200]
