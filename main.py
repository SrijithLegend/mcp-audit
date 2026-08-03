import importlib.metadata

import typer

__version__ = importlib.metadata.version("mcp-audit")

app = typer.Typer()


@app.command()
def hello(name: str):
    """Say hello"""
    print(f"Hello {name}!")


@app.command()
def goodbye(name: str):
    """Say goodbye"""
    print(f"Bye {name}!")


@app.command()
def version():
    """Show the version of the application"""
    print(f"mcp-audit version {__version__}")


if __name__ == "__main__":
    app()
