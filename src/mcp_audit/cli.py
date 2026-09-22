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

# Exit codes, so scan can gate a pipeline. SUSPECTED deliberately passes:
# the thresholds say it is a gap worth looking at, not one worth failing a
# build over. Gate on it yourself with --json if you want it stricter.
EXIT_CODE = {"CONFIRMED": 1, "SUSPECTED": 0, "CLEAN": 0}


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
    result = audit(command, args or [], task, trials)
    print(json.dumps(result, indent=2) if as_json else render(result, result["target"], MODEL))
    raise typer.Exit(EXIT_CODE[result["verdict"]])


def audit(command: str, args: list[str], task: str = DEFAULT_TASK, trials: int = TRIALS) -> dict:
    """The pipeline, with real defaults.

    Kept out of the typer command: called as a plain function, a command's
    defaults are typer OptionInfo objects, not the values you declared -- so
    anything that tests the pipeline has to come through here.
    """
    inventory = asyncio.run(fetch_inventory(command, args))
    real = run_trials(inventory, task, trials)
    sanitized = run_trials(sanitize(inventory), task, trials)
    # what was run belongs in the artifact -- a verdict with no task or model
    # attached is not reproducible six months later
    return diff(real, sanitized) | {
        "target": " ".join([command, *args]),
        "model": MODEL,
        "task": task,
    }


if __name__ == "__main__":
    app()
