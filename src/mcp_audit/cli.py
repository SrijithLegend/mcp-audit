import asyncio
import json
from importlib.metadata import version as _pkg_version

import typer

from .client import fetch_inventory
from .differ import diff
from .harness import DEFAULT_TASK, TRIALS, run_trial, run_trials
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
):
    """Audit a server: run the same task with and without its prose, diff what the model did"""
    inventory = asyncio.run(fetch_inventory(command, args or []))
    real = run_trials(inventory, task, trials)
    sanitized = run_trials(sanitize(inventory), task, trials)
    print(json.dumps(diff(real, sanitized), indent=2))


if __name__ == "__main__":
    app()
