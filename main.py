import asyncio
import json

import typer

from client import fetch_inventory

__version__ = "1.0.0"

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
    print(f"mcp-audit version {__version__}")

if __name__ == "__main__":
    app()