import asyncio
import json
from importlib.metadata import version as _pkg_version

import typer

from .client import fetch_inventory
from .harness import DEFAULT_TASK, run_trial

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


if __name__ == "__main__":
    app()
