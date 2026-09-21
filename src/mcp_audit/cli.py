import asyncio
import json
from importlib.metadata import version as _pkg_version

import typer

from .client import fetch_inventory

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


if __name__ == "__main__":
    app()
