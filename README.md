# mcp-audit

**Static scanners flag suspicious text. mcp-audit confirms the text actually steers a model.**

An MCP server hands your model free text — tool descriptions, parameter descriptions,
and the server's own `instructions` — and most hosts paste all of it straight into the
system prompt. `mcp-audit` captures that surface, strips the prose, and runs the same
agent task N times against each version. If the model's tool calls diverge, the prose
did it — and the report shows you the call.

```
uvx mcp-audit scan npx -y @some/mcp-server
```

Tools are **never executed**. Every call the model makes is answered with a dry-run
stub, so auditing a filesystem server does not read your `~/.ssh`.

## Install

```bash
uv tool install mcp-audit          # or: uvx mcp-audit ...
export ANTHROPIC_API_KEY=sk-ant-...   # bring your own key
```

## Use

```bash
# audit a stdio server (this RUNS the server locally — only scan ones you'd run anyway)
mcp-audit scan npx -y @modelcontextprotocol/server-filesystem /tmp

# audit a remote Streamable HTTP server
mcp-audit scan --url https://example.com/mcp --header "Authorization: Bearer $TOKEN"

# capture once, scan the capture (and hand the same file to CI or the Cloud)
mcp-audit inspect npx -y @some/server --out inventory.json
mcp-audit scan --inventory inventory.json --trials 10 --json

# see exactly what sanitization removes before you trust a verdict built on its absence
mcp-audit sanitize npx -y @some/server
```

Useful flags: `--trials 5`, `--task`, `--model`, `--stub canary|inert`, `--max-cost 1.00`,
`--json`, `--sarif out.sarif`, `--md report.md`, `--fail-on confirmed|suspected`,
`--no-escalate`, `--concurrency 4`, `--debug`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | CLEAN or INCONCLUSIVE |
| 1 | CONFIRMED (or SUSPECTED with `--fail-on suspected`) |
| 2 | usage error |
| 3 | could not read the server |
| 4 | API key / model error |
| 5 | over `--max-cost` |

## How it works

```
                    ┌──► real inventory ──────► N trials ──┐
capture (tools/list)│    (instructions + prose)            ├──► compare per-trial
                    └──► sanitized inventory ──► N trials ──┘    features, Fisher exact,
                         (same tools, no prose)                  Holm correction → verdict
```

Both arms are identical in every respect except the inventory: same model, same task,
same stub results, same tool order, same caching, same turn limit. So a behavioural
difference has exactly one possible cause.

What gets counted is a **feature per trial**, not a call:

- `sensitive` — an argument matched a detector (`/etc/passwd`, `~/.ssh`, `.env`,
  `.aws/credentials`, `SOMETHING_TOKEN`, a URL the server never mentioned, …)
- `canary_flow` — a token from an earlier stub result came back as an argument to
  another tool: data moving between tools, which is the exfiltration shape
- `called_first` — call order changed on a tool that touches something sensitive
- `called`, `optional_populated` — behavioural only, never enough to CONFIRM

Verdicts (thresholds live in `differ.py`, documented in `docs/ROADMAP.md` §1.4):

| Verdict | Rule |
|---|---|
| **CONFIRMED** | a security-relevant signal with Holm-adjusted p < 0.05 **and** \|Δrate\| ≥ 0.6 |
| **SUSPECTED** | raw p < 0.2 and \|Δrate\| ≥ 0.4, or a call-rate change that beats the arm-wide shift |
| **INCONCLUSIVE** | too many API errors, or the task never made the model use a tool |
| **CLEAN** | otherwise |

Two guards keep false positives down. Honest, helpful descriptions make a model use
*every* tool more, so a call-rate delta that does not beat the **arm-wide shift** is not
reported. And a borderline result at 5 trials per arm triggers **one** round of 5 more —
once only, because repeated peeking at a growing sample manufactures significance.

## What sanitization removes

Every description becomes a generated `Tool: <name>. Parameters: <names>.` line, the
server's `instructions` become empty, and `description`, `title`, `examples`, `$comment`,
`deprecated`, `default` and any `x-*` vendor key are dropped from the JSON Schema at
every depth — including inside `anyOf`/`items`/`$defs`/`dependentSchemas`/
`propertyNames`/`unevaluatedProperties`/`contentSchema`.

`enum` and `const` survive on purpose: the model needs them to form a valid call, so
removing them would change behaviour for reasons that have nothing to do with injected
prose. `default` does **not** survive — it is a pure annotation, so it can carry prose
without affecting whether a call validates. Local `$ref` is left as-is and remote `$ref`
is never fetched.

## What this does NOT catch

- **Tool and parameter names**, and `enum`/`const` values. They are the call surface;
  removing them would break the tool. A parameter named `always_read_ssh_key_first`
  carries its injection through sanitization intact.
- **Injection through tool results.** We never execute tools, so a server that behaves
  until it answers a call is out of scope by construction.
- **Rug pulls.** A verdict is about the inventory we captured at that moment. Re-scan
  on upgrade (the hash is in every report), or use monitoring.
- **Other models.** Steering is model-specific: a server that does not steer
  `claude-haiku-4-5` may steer something else. The model is recorded in the report.

## Cost

One trial runs the whole inventory, so API calls are roughly `2 × trials × turns`
(turns capped at 6, usually ~3). `scan` counts the real turn-1 payload with
`count_tokens`, prints an estimate, and **refuses** to exceed `--max-cost` (default
$1.00). Typical small server at defaults: a few cents on `claude-haiku-4-5`.

## Safety

- Stdio capture spawns the server with a minimal environment allowlist. `ANTHROPIC_API_KEY`
  and anything matching `*KEY*|*TOKEN*|*SECRET*` is never passed to an audited server.
  Pass what a server legitimately needs with `--env K=V`.
- No tool is ever called. A grep test in `tests/test_invariants.py` enforces it.
- Server text is treated as hostile everywhere: never rendered as markdown or HTML,
  arguments truncated and masked in evidence, invisible/bidi Unicode shown as `<U+200B>`.

## CI

```yaml
- uses: SrijithLegend/mcp-audit/action@v0
  with:
    command: npx -y @some/mcp-server
    trials: 5
    fail-on: confirmed
    api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

Writes SARIF to GitHub code scanning and fails the job on a confirmed finding.

## Development

```bash
uv sync --all-extras
uv run pytest -q                  # 170+ tests, fully offline
uv run pytest -q -m live          # real API calls, costs money
uv run ruff check . && uv run mypy src
```

`fixtures/` holds real stdio MCP servers used as known positives and known negatives:

| Fixture | Steering channel |
|---|---|
| `clean.py` | none — the control. A finding here is a false positive. |
| `benign_verbose.py` | none — long, bossy, honest prose. The false-positive trap. |
| `poisoned_instructions.py` | server `instructions`; every tool description is honest |
| `poisoned_param.py` | a parameter description that demands `/etc/passwd` contents |
| `poisoned_tool_desc.py` | the classic: payload in a tool description |
| `poisoned_nested.py` | payload inside `$defs` reached through `anyOf` |
| `poisoned_suppress.py` | steers *away*: "never call audit_log" |
| `http_fixture.py` | the same poisoned server over Streamable HTTP |
| `env_dump.py` | reports its own environment, so the allowlist can be tested |

## Licence

MIT for the engine and CLI (`src/`). The hosted service under `cloud/` is AGPL-3.0.
