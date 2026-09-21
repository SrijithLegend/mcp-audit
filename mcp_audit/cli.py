import asyncio
import json
from importlib.metadata import version as _pkg_version

import typer

from .client import fetch_inventory

app = typer.Typer()

@app.command()
def scan(command: str, args: list[str] = typer.Argument(None)):
    """Scan an MCP server's tool inventory"""
    inventory = asyncio.run(fetch_inventory(command, args or []))
    print(json.dumps(inventory, indent=2))

@app.command()
def report():
    """Generate a report"""
    print("Generating report...")

@app.command()
def version():
    """Show the version of the application"""
    print(f"mcp-audit version {_pkg_version('mcp-audit')}")

if __name__ == "__main__":
    app()
