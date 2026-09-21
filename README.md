# mcp-audit

Differential exploit confirmation for MCP servers.

An MCP server hands your model free text — tool descriptions, parameter
descriptions, and the server's own `instructions` — and most hosts paste all of
it straight into the system prompt. `mcp-audit` captures that surface, strips
the prose, and compares how a model behaves with and without it. A behavior
change is the confirmation: the prose, not the tool, drove the call.

## Install

```
uv pip install -e .
```

## Use

```
mcp-audit inspect npx -y @modelcontextprotocol/server-filesystem /tmp
mcp-audit version
```

`inspect` prints the raw inventory as JSON: the server `instructions`, plus each
tool's name, description, and input schema.

## What sanitization removes

`mcp_audit.sanitizer` replaces every description with a generated
`Tool: <name>. Parameters: <names>.` line and recursively drops
`description`, `title`, `examples`, `$comment`, `deprecated`, and any `x-*`
vendor key from the JSON Schema — at every nesting depth, including inside
`anyOf`/`items`/`$defs`.

`enum`, `const`, and `default` survive on purpose. The model needs them to form
a valid call, so removing them would change behavior for reasons that have
nothing to do with injected prose.

## Known limitation: parameter names

Sanitization cannot remove parameter *names* — they are the call surface. A
server exposing a parameter named `always_read_ssh_key_first` carries its
injection through `_minimal()` intact. This is not fixable without breaking the
tool. Treat parameter names as an uncontrolled channel when reading results.

## Self-checks

Each module carries its own assert-based check:

```
python -m mcp_audit.sanitizer   # prose stripped at depth, call surface intact
python -m mcp_audit.client      # scans a throwaway stub server
```
