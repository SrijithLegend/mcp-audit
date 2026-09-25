"""The CLI. Thin on purpose: parse, call the engine, print, exit with a code.

Exit codes are a contract (ROADMAP §1.7): 0 clean/inconclusive, 1 confirmed,
2 usage, 3 capture failure, 4 API/auth, 5 over budget. Every failure is one line.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.console import Console

from .audit import audit as run_audit
from .audit import engine_version, exit_code
from .capture.http import capture_http, parse_headers
from .capture.stdio import capture_stdio, parse_env
from .dryrun import MODES, cast_mode
from .errors import AuditError, UsageError
from .harness import CONCURRENCY, DEFAULT_TASK, MODEL, TRIALS, client
from .models import Inventory, Report
from .report import render, to_json, to_markdown, to_sarif
from .sanitizer import sanitize, stripped_diff

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Differential exploit confirmation for MCP servers.\n\n"
        "Scanning a stdio server RUNS it on this machine. Only scan servers you would "
        "be willing to run anyway. Tools are never executed: every call the model makes "
        "is answered with a dry-run stub."
    ),
)
err = Console(stderr=True)


def _fail(exc: AuditError) -> NoReturn:
    err.print(f"[red]error:[/red] {exc}")
    raise typer.Exit(exc.exit_code)


def _capture(
    command: str | None,
    args: list[str] | None,
    url: str | None,
    inventory_file: Path | None,
    headers: list[str] | None,
    env: list[str] | None,
    cwd: str | None,
    debug: bool,
) -> Inventory:
    """One of three sources, never two."""
    chosen = [bool(command), bool(url), bool(inventory_file)]
    if sum(chosen) != 1:
        raise UsageError("Give exactly one of: a command to run, --url, or --inventory FILE.")
    if inventory_file:
        try:
            return Inventory.model_validate_json(inventory_file.read_text(encoding="utf-8"))
        except OSError as exc:
            raise UsageError(f"Cannot read {inventory_file}: {exc}") from exc
        except ValueError as exc:
            raise UsageError(f"{inventory_file} is not a valid mcp-audit inventory: {exc}") from exc
    if url:
        return asyncio.run(capture_http(url, headers=parse_headers(headers)))
    inventory, stderr_tail = asyncio.run(capture_stdio(str(command), args or [], env=parse_env(env), cwd=cwd))
    if debug and stderr_tail:
        for line in stderr_tail:
            err.print(f"[dim]server stderr:[/dim] {line}")
    return inventory


@app.command()
def version() -> None:
    """Show the version."""
    print(f"mcp-audit {engine_version()}")


@app.command()
def inspect(
    command: str | None = typer.Argument(None, help="Command that starts the stdio server"),
    args: list[str] | None = typer.Argument(None, help="Arguments for that command"),
    url: str | None = typer.Option(None, "--url", help="Streamable HTTP endpoint instead"),
    header: list[str] | None = typer.Option(None, "--header", help="'Name: value', repeatable"),
    env: list[str] | None = typer.Option(None, "--env", help="K=V passed to the server, repeatable"),
    cwd: str | None = typer.Option(None, "--cwd", help="Working directory for the server"),
    out: Path | None = typer.Option(None, "--out", help="Write the inventory JSON here"),
    debug: bool = typer.Option(False, "--debug", help="Show the server's stderr"),
) -> None:
    """Capture a server's inventory (instructions, tools, schemas) as JSON."""
    try:
        inventory = _capture(command, args, url, None, header, env, cwd, debug)
    except AuditError as exc:
        _fail(exc)
    text = json.dumps(inventory.model_dump(mode="json"), indent=2, ensure_ascii=False)
    if out:
        out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {out} ({inventory.sha256()[:12]}, {len(inventory.tools)} tools)")
    else:
        print(text)


@app.command("sanitize")
def sanitize_cmd(
    command: str | None = typer.Argument(None),
    args: list[str] | None = typer.Argument(None),
    url: str | None = typer.Option(None, "--url"),
    inventory_file: Path | None = typer.Option(None, "--inventory"),
    header: list[str] | None = typer.Option(None, "--header"),
    env: list[str] | None = typer.Option(None, "--env"),
    cwd: str | None = typer.Option(None, "--cwd"),
    as_json: bool = typer.Option(False, "--json", help="Print the sanitized inventory instead"),
    debug: bool = typer.Option(False, "--debug"),
) -> None:
    """Show what sanitization removes -- the prose a verdict rests on being gone."""
    try:
        inventory = _capture(command, args, url, inventory_file, header, env, cwd, debug)
    except AuditError as exc:
        _fail(exc)
    clean = sanitize(inventory)
    if as_json:
        print(json.dumps(clean.model_dump(mode="json"), indent=2, ensure_ascii=False))
    else:
        print(stripped_diff(inventory, clean))


@app.command()
def scan(
    command: str | None = typer.Argument(None, help="Command that starts the stdio server"),
    args: list[str] | None = typer.Argument(None, help="Arguments for that command"),
    url: str | None = typer.Option(None, "--url", help="Streamable HTTP endpoint instead"),
    inventory_file: Path | None = typer.Option(
        None, "--inventory", help="Scan a previously captured inventory JSON"
    ),
    header: list[str] | None = typer.Option(None, "--header", help="'Name: value', repeatable"),
    env: list[str] | None = typer.Option(None, "--env", help="K=V passed to the server, repeatable"),
    cwd: str | None = typer.Option(None, "--cwd"),
    trials: int = typer.Option(TRIALS, "--trials", min=2, max=50, help="Runs per arm. One run is noise."),
    task: str = typer.Option(DEFAULT_TASK, "--task", help="What to ask the model to do."),
    model: str = typer.Option(MODEL, "--model"),
    stub: str = typer.Option("canary", "--stub", help=f"Stub result mode: {' | '.join(MODES)}"),
    concurrency: int = typer.Option(CONCURRENCY, "--concurrency", min=1, max=16),
    max_cost: float = typer.Option(1.00, "--max-cost", help="Hard stop on estimated spend, USD"),
    yes: bool = typer.Option(False, "--yes", help="Accept the cost estimate without prompting"),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable report on stdout"),
    sarif: Path | None = typer.Option(None, "--sarif", help="Write SARIF 2.1.0 here"),
    md: Path | None = typer.Option(None, "--md", help="Write a markdown report here"),
    fail_on: str = typer.Option("confirmed", "--fail-on", help="confirmed | suspected"),
    no_escalate: bool = typer.Option(False, "--no-escalate", help="Never run extra trials"),
    push: bool = typer.Option(
        False,
        "--push",
        help="After scanning, upload the report to mcp-audit Cloud for history and monitoring",
    ),
    debug: bool = typer.Option(False, "--debug", help="Show tracebacks and server stderr"),
) -> None:
    """Audit a server: run the same task with and without its prose, diff what the model did."""
    try:
        if fail_on not in ("confirmed", "suspected"):
            raise UsageError("--fail-on takes 'confirmed' or 'suspected'.")
        if stub not in MODES:
            raise UsageError(f"--stub takes one of: {', '.join(MODES)}")
        inventory = _capture(command, args, url, inventory_file, header, env, cwd, debug)
        interactive = sys.stdout.isatty()
        note = None if as_json else (lambda line: err.print(f"[dim]{line}[/dim]"))
        report = asyncio.run(
            run_audit(
                inventory,
                api=client(),
                task=task,
                trials=trials,
                model=model,
                stub_mode=cast_mode(stub),
                concurrency=concurrency,
                max_cost=max_cost,
                assume_yes=yes,
                interactive=interactive,
                escalate=not no_escalate,
                progress=note,
            )
        )
    except AuditError as exc:
        if debug:
            raise
        _fail(exc)

    _emit(report, as_json, sarif, md)
    if push:
        # The audit is already done and its artefacts are written; an upload that fails must
        # not lose the result or change the exit code the pipeline gates on.
        from .cloud import push_report

        try:
            url = push_report(report, inventory=inventory, progress=note)
            if not as_json:
                err.print(f"[dim]report stored at {url}[/dim]")
        except AuditError as exc:
            err.print(f"[yellow]warning:[/yellow] scan succeeded but the upload failed: {exc}")
    raise typer.Exit(exit_code(report, fail_on))


def _emit(report: Report, as_json: bool, sarif: Path | None, md: Path | None) -> None:
    """Write the requested artefacts, then the report itself."""
    if sarif:
        sarif.write_text(to_sarif(report) + "\n", encoding="utf-8")
    if md:
        md.write_text(to_markdown(report) + "\n", encoding="utf-8")
    print(to_json(report) if as_json else render(report), end="" if as_json else "\n")


@app.command(hidden=True)
def trial(
    command: str | None = typer.Argument(None),
    args: list[str] | None = typer.Argument(None),
    url: str | None = typer.Option(None, "--url"),
    inventory_file: Path | None = typer.Option(None, "--inventory"),
    task: str = typer.Option(DEFAULT_TASK, "--task"),
    model: str = typer.Option(MODEL, "--model"),
    sanitized: bool = typer.Option(False, "--sanitized", help="Run the sanitized arm instead"),
) -> None:
    """One trial, printed as JSON. Debugging aid, not a verdict."""
    from .harness import run_trial

    try:
        inventory = _capture(command, args, url, inventory_file, None, None, None, False)
        side = "sanitized" if sanitized else "real"
        trace = asyncio.run(
            run_trial(
                sanitize(inventory) if sanitized else inventory,
                side=side,
                trial=0,
                task=task,
                api=client(),
                model=model,
            )
        )
    except AuditError as exc:
        _fail(exc)
    print(json.dumps(trace.model_dump(mode="json"), indent=2, ensure_ascii=False))


@app.command()
def login(
    token: str | None = typer.Option(None, "--token", help="Paste an mcpa_ token from the web app"),
) -> None:
    """Store an mcp-audit Cloud token for `scan --push`."""
    from .credentials import store, token_page

    if not token:
        print(f"Create a token at {token_page()} and re-run: mcp-audit login --token mcpa_...")
        raise typer.Exit(2)
    if not token.startswith("mcpa_"):
        _fail(UsageError("That does not look like an mcp-audit token (they start with mcpa_)."))
    path = store(token)
    print(f"Stored. ({path})")


def main() -> Any:  # pragma: no cover - entry point
    return app()


if __name__ == "__main__":  # pragma: no cover
    app()
