# Capture compatibility

`uv run python bench/run.py --dry-run --name-servers` — captures each server's inventory
and stops. **No model calls, no cost, no verdicts**, so naming the servers here discloses
nothing: a tool count is not a finding.

Measured 2026-09-24, engine 0.1.0, mcp SDK 2.2.0, on Windows 11 / Python 3.11.

| Server | Tools | Version | Result |
|---|---|---|---|
| `@modelcontextprotocol/server-filesystem` | 14 | 0.2.0 | captured |
| `@modelcontextprotocol/server-memory` | 9 | 0.6.3 | captured |
| `@modelcontextprotocol/server-everything` | 13 | 2.0.0 | captured |
| `mcp-server-git` | 12 | 1.30.0 | captured |
| `mcp-server-fetch` | 1 | 1.30.0 | captured |
| `mcp-server-sqlite` | — | — | **failed to start** (see below) |
| `mcp-server-time` | 2 | 1.30.0 | captured |
| `@modelcontextprotocol/server-sequential-thinking` | 1 | — | captured |
| `@modelcontextprotocol/server-puppeteer` | 7 | — | captured |
| `@modelcontextprotocol/server-github` | 26 | — | captured |
| `fixtures/clean.py` | 3 | — | captured (control) |
| `fixtures/benign_verbose.py` | 3 | — | captured (control) |

11 of 12. Worth noting for what it exercises: 26 tools on one server, a server with a
single tool, and schemas from four different SDK generations — the shapes that would break
a capture layer written against one example.

## The failure, and why it is a good sign

`mcp-server-sqlite` does not start against the current MCP SDK — its own code calls
`server.list_resources()`, which that SDK version no longer has. Nothing to do with us.

What matters is what the user sees:

```
error: uvx failed during MCP handshake: MCPError: Connection closed
Last stderr: ... AttributeError: 'Server' object has no attribute 'list_resources'
```

One line, exit code 3, and the server's own traceback tail — which is the actual cause.
That is the behaviour `docs/ROADMAP.md` §1.2 asks for ("show last 5 stderr lines"), proven
against a real broken server rather than a fixture designed to fail.

## What this does not tell you

Nothing about verdicts. Capture working means we can read a server's advertised surface; it
says nothing about whether that surface steers a model. That is Gate 1 (fixtures) and
§2.1 (this same list, with the model running), and neither has been measured yet — see
`bench/fixtures.md` and `PROGRESS.md`.
