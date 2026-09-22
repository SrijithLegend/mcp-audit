import asyncio
import json
from importlib.metadata import version as _pkg_version

import typer

from .client import fetch_inventory
from .differ import diff
from .harness import DEFAULT_TASK, MODEL, TRIALS, run_trial, run_trials
from .report import render
from .sanitizer import sanitize

app = typer.Typer()


@app.command()
def inspect(command: str, args: list[str] = typer.Argument(None)):
    """Dump an MCP server's raw tool inventory as JSON"""
    inventory = asyncio.run(fetch_inventory(command, args or []))
    print(json.dumps(inventory, indent=2))


@app.command()
def version():
    """Show the version of the application"""
    print(f"mcp-audit version {_pkg_version('mcp-audit')}")


@app.command()
def trial(
    command: str,
    args: list[str] = typer.Argument(None),
    task: str = typer.Option(DEFAULT_TASK, help="What to ask the model to do. It needs a reason to use tools."),
):
    """Run one agent trial against a server and print the tool-call trace"""
    inventory = asyncio.run(fetch_inventory(command, args or []))
    print(json.dumps(run_trial(inventory, task), indent=2))


@app.command()
def scan(
    command: str,
    args: list[str] = typer.Argument(None),
    task: str = typer.Option(DEFAULT_TASK, help="What to ask the model to do. It needs a reason to use tools."),
    trials: int = typer.Option(TRIALS, help="Runs per side. One run is noise."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output, for CI and scripting."),
):
    """Audit a server: run the same task with and without its prose, diff what the model did"""
    inventory = asyncio.run(fetch_inventory(command, args or []))
    real = run_trials(inventory, task, trials)
    sanitized = run_trials(sanitize(inventory), task, trials)
    target = " ".join([command, *(args or [])])
    # what was run belongs in the artifact -- a verdict with no task or model
    # attached is not reproducible six months later
    result = diff(real, sanitized) | {"target": target, "model": MODEL, "task": task}
    print(json.dumps(result, indent=2) if as_json else render(result, target, MODEL))


if __name__ == "__main__":
    app()
