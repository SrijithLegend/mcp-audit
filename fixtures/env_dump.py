"""Reports its own environment back through MCP, so a test can prove the allowlist.

The env keys ride in the server's `instructions` field because that is the one
channel the capture path already returns verbatim -- no stderr parsing, no temp
files. A malicious server could read our secrets exactly this cheaply, which is
the point of the test.
"""

import os

from mcp.server.mcpserver import MCPServer

m = MCPServer("env-dump", instructions="ENV_KEYS=" + ",".join(sorted(os.environ)))


@m.tool(description="Does nothing.")
def noop() -> str:
    return "ok"


if __name__ == "__main__":
    m.run()
