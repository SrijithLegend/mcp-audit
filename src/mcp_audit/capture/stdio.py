"""Capture over stdio: spawn the server, initialize, list tools, kill it.

This runs the user's command on the user's machine. That is their choice and the
docs say so plainly -- but it is also why the environment we hand the child is an
allowlist (CLAUDE.md invariant 4). An audited server has no business seeing
`ANTHROPIC_API_KEY`, and a malicious one would exfiltrate it on sight.

Never used by the Cloud. `tests/test_invariants.py` greps `cloud/` to prove it.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from typing import IO, Any, TextIO, cast

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..errors import CaptureError, describe, first_leaf
from ..models import Inventory
from .paginate import collect_tools

TIMEOUT = 30.0

#: Keys the child is allowed to inherit. PATH/HOME/LANG are the documented minimum;
#: the Windows entries are what the interpreter itself needs to start at all, and
#: none of them can hold a credential.
ALLOWED_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
ALLOWED_ENV_WINDOWS = (
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMFILES",
    "PROGRAMDATA",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
)

#: Anything matching this never leaves our process, whatever the allowlist says.
SECRET_KEY = re.compile(r"(?i)key|token|secret|password|passwd|credential|auth")

STDERR_LINES = 5


def minimal_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The child's environment: an allowlist, plus what the user passed explicitly.

    `extra` comes from `--env K=V`, so the user can hand a server the one API key it
    genuinely needs without handing it everything else in their shell.
    """
    names = ALLOWED_ENV + (ALLOWED_ENV_WINDOWS if os.name == "nt" else ())
    env = {k: os.environ[k] for k in names if k in os.environ and not SECRET_KEY.search(k)}
    env.update(extra or {})
    return env


def parse_env(pairs: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise CaptureError(f"--env expects K=V, got {pair!r}")
        key, value = pair.split("=", 1)
        out[key] = value
    return out


async def capture_stdio(
    command: str,
    args: list[str] | None = None,
    *,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    timeout: float = TIMEOUT,
) -> tuple[Inventory, list[str]]:
    """Returns the inventory and the server's stderr tail (shown only with --debug)."""
    args = args or []
    params = StdioServerParameters(command=command, args=args, env=minimal_env(env), cwd=cwd)
    source = " ".join([command, *args])
    # A real file, not a pipe we forget to drain: a chatty server that fills a pipe
    # buffer would deadlock on startup, and the tail is what makes a crash debuggable.
    with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as errlog:
        try:
            with anyio.fail_after(timeout):
                async with (
                    stdio_client(params, errlog=cast("TextIO", errlog)) as (read, write),
                    ClientSession(read, write) as session,
                ):
                    init = await session.initialize()
                    tools = await collect_tools(session)
        except CaptureError:
            raise
        except Exception as exc:
            # anyio wraps transport failures in an ExceptionGroup; the first leaf is
            # the one that actually explains the failure.
            leaf = first_leaf(exc)
            if isinstance(leaf, TimeoutError):
                raise CaptureError(
                    f"{command} did not finish initialize + tools/list within {timeout:g}s."
                    + _tail_hint(errlog)
                ) from exc
            if isinstance(leaf, FileNotFoundError):
                raise CaptureError(f"Command not found: {command}") from exc
            raise CaptureError(
                f"{command} failed during MCP handshake: {describe(leaf)}" + _tail_hint(errlog)
            ) from exc
        stderr_tail = _tail(errlog)

    return Inventory.from_initialize(init, tools, f"stdio: {source}"), stderr_tail


def _tail(errlog: Any) -> list[str]:
    try:
        errlog.seek(0)
        return [line.rstrip() for line in errlog.read().splitlines() if line.strip()][-STDERR_LINES:]
    except Exception:  # pragma: no cover - a closed temp file is not worth a crash
        return []


def _tail_hint(errlog: Any) -> str:
    lines = _tail(errlog)
    return ("\nLast stderr: " + " | ".join(lines)) if lines else ""


def python_command() -> str:
    """The interpreter running us -- what the fixtures are spawned with."""
    return sys.executable
