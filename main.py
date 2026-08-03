import typer

__version__ = "1.0.0"

app = typer.Typer()

@app.command()
def scan():
    """Scan for issues"""
    print("Scanning for issues...")

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