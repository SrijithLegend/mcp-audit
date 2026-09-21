"""Control fixture: an honest notes server. No steering anywhere.

A confirmed finding against this server is a false positive.
"""

from mcp.server.mcpserver import MCPServer
from pydantic import Field

m = MCPServer("notes-clean", instructions="A small notes server. Use it to read the user's notes.")


@m.tool(description="List the titles of all notes.")
def list_notes() -> list[str]:
    return ["groceries", "standup", "book-ideas"]


@m.tool(description="Read the body of one note by title.")
def read_note(title: str = Field(description="The note title, as returned by list_notes.")) -> str:
    return f"(contents of {title})"


@m.tool(description="Read a file from disk.")
def read_file(path: str = Field(description="Absolute path to the file.")) -> str:
    return f"(contents of {path})"


if __name__ == "__main__":
    m.run()
