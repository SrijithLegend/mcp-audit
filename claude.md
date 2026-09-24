# CLAUDE.md — mcp-audit

Read this whole file at the start of every session. Then read `PROGRESS.md` to see
which phase you are in. The detailed specs are in `docs/ROADMAP.md` (what to build,
per phase, with exit gates) and `docs/SECURITY.md` (threat model and required
controls). Read the section of ROADMAP for the current phase before writing code.

## What this project is

`mcp-audit` confirms whether an MCP server's free text (server `instructions`, tool
descriptions, parameter descriptions, schema annotations) **actually steers a model**.
It does that differentially: run the same agent task N times against the real
inventory and N times against a sanitized one (prose stripped, call surface kept),
then compare the tool-call traces. A statistically significant, security-relevant
divergence is the confirmation.

Differentiator vs static scanners (Invariant/Snyk `mcp-scan` / `agent-scan`): they flag
suspicious text; we confirm behavior change. The pitch lives or dies on a
**lower false-positive rate on the same servers**. Every design decision serves that.

Two products, one engine:

| Product | What | License | Who pays for LLM calls |
|---|---|---|---|
| **CLI** (`src/mcp_audit/`, PyPI) | Full engine, local capture, BYOK | MIT | User's own `ANTHROPIC_API_KEY` |
| **Cloud** (`cloud/`) | Hosted scans, history, rug-pull monitoring, CI integration, teams, billing | see `cloud/LICENSE` (decision D7) | Us — metered by plan |

The CLI must never be crippled to push people to Cloud. Cloud sells convenience,
history, monitoring and teams — not the core verdict.

## Repository layout (target)

```
src/mcp_audit/          # engine + CLI. Published to PyPI. No web/db deps here, ever.
  cli.py                # Typer app: inspect, sanitize, scan, trial (hidden), version, login
  models.py             # Inventory, Tool, Trace, ToolCall, Finding, Verdict, Report (pydantic v2)
  capture/stdio.py      # spawn + initialize + tools/list over stdio (local only)
  capture/http.py       # Streamable HTTP capture (CLI + Cloud; Cloud wraps it in ssrf guard)
  sanitizer.py          # prose stripping (exists)
  dryrun.py             # stub results + canary tokens (exists; extend, keep invariant)
  harness.py            # agent loop (exists; make async, cached, concurrent)
  differ.py             # per-tool / per-feature rates, Fisher exact, verdicts
  features.py           # sensitive-arg detectors, canary flow, first-call, optional-param-populated
  stats.py              # fisher_exact (math.comb, no scipy), holm correction
  cost.py               # token counting + $ estimate + budget guard
  report/{terminal,json,markdown,sarif}.py
  errors.py             # typed errors -> one-line messages + exit codes
fixtures/               # stdio fixture servers (known positives + clean control)
tests/                  # pytest; unit + fixture e2e (fake client) + live (opt-in)
bench/                  # real-server results, head-to-head vs mcp-scan (Phase 2)
action/                 # GitHub Action (composite) (Phase 2)
cloud/
  api/                  # FastAPI app (package: mcp_audit_cloud)
  worker/               # arq worker: runs scans, monitors
  web/                  # Next.js frontend
  infra/                # Dockerfiles, fly.toml, docker-compose.yml for local dev
docs/ROADMAP.md  docs/SECURITY.md  PROGRESS.md
```

## Non-negotiable invariants (break one = stop and ask)

1. **No live tool execution. Ever.** Nothing in `src/` or `cloud/` may call
   `call_tool`/`session.call*` on an audited server. Every model tool call is answered
   by `dryrun`. The grep test in `tests/test_invariants.py` enforces this and must
   never be weakened, skipped, or given an allowlist entry.
2. **The two arms differ only in the inventory.** Same model, task, temperature,
   max_turns, stub behavior, system scaffolding, tool order. If you add anything to the
   prompt, it goes on both sides identically. A test asserts the request payloads of
   the two arms differ only in `tools[*].description`, schema prose, and `system`.
3. **The Cloud never executes user-supplied code.** Cloud accepts (a) an inventory JSON
   captured by the user's CLI, or (b) an `https://` Streamable HTTP URL fetched through
   the SSRF guard. Stdio in the cloud is forbidden — no "just this once", no sandbox
   shortcut. See SECURITY.md §2.
4. **Audited servers never see our secrets.** Stdio servers are spawned with a minimal
   env allowlist (`PATH`, `HOME`, `LANG`, plus explicit `--env K=V` from the user).
   `ANTHROPIC_API_KEY` and anything matching `*KEY*|*TOKEN*|*SECRET*` is never passed.
   Tested.
5. **Attacker-controlled text is data.** Tool descriptions, instructions, model tool
   arguments are hostile. Never render them as HTML/markdown, never interpolate them
   into shell, SQL, log format strings, or our own LLM prompts outside the harness.
6. **Verdict thresholds are specified, not tuned by vibes.** They live in
   `differ.py` constants, are documented in ROADMAP §1.4, and changing them requires
   re-running the fixture gate and updating `bench/`. Ask before changing.
7. **Money guards are hard stops.** CLI refuses to exceed `--max-cost`. Cloud checks
   plan quota atomically *before* enqueue and has a global daily spend breaker.

## Decisions already made (don't relitigate; flag if you find a real problem)

| # | Decision | Why |
|---|---|---|
| D1 | Python 3.11+, `uv`, hatchling, src layout | Existing |
| D2 | Engine deps stay minimal: `anthropic`, `mcp>=2.2,<3`, `typer`, `pydantic>=2`, `rich`, `httpx2` | PyPI install must stay light |
| D3 | Default model `claude-haiku-4-5`, `--model` to override. Report records model | We count calls, not judge prose |
| D4 | Default 5 trials/arm, adaptive escalation to 10 when borderline (ROADMAP §1.4) | Stochasticity |
| D5 | Cloud API: FastAPI + SQLAlchemy 2 (async) + Alembic + Postgres 16; queue: arq + Redis | Reuses Python engine directly |
| D6 | Frontend: Next.js (App Router) + TypeScript strict + Tailwind + shadcn/ui + TanStack Query | Standard, fast to ship |
| D7 | `cloud/` license: AGPL-3.0 (engine stays MIT) | Blocks closed hosted clones; Srijith may switch to a private repo |
| D8 | Auth: Clerk (GitHub + email login), API verifies Clerk JWT via JWKS. CI uses our own API tokens (`mcpa_` prefix, sha256-hashed) | Don't roll auth |
| D9 | Billing: **Dodo Payments** (Merchant of Record) behind a `BillingProvider` interface; Polar as fallback adapter | Stripe India is invite-only; MoR handles global tax |
| D10 | Hosting: web on Vercel; api + worker on Fly.io; Postgres on Neon; Redis on Upstash | Cheap, managed |
| D11 | Email: Resend. Errors: Sentry. Logs: structlog JSON | |
| D12 | Cloud never supports BYOK — we don't store customer LLM keys | Fewer secrets to lose |

## Commands

```bash
uv sync --all-extras                 # install engine + dev deps
uv run pytest -q                     # unit + fixture tests (offline, fake client)
uv run pytest -q -m live             # live tests: needs ANTHROPIC_API_KEY, costs money, ask first
uv run ruff check . && uv run ruff format --check .
uv run mypy src                      # strict on src/mcp_audit
uv run mcp-audit scan python fixtures/poisoned_instructions.py --trials 5
uv run mcp-audit inspect --url https://example.com/mcp --header "Authorization: Bearer $T"

# cloud (Phase 3+)
docker compose -f cloud/infra/docker-compose.yml up -d   # postgres + redis
uv run --directory cloud/api alembic upgrade head
uv run --directory cloud/api uvicorn mcp_audit_cloud.main:app --reload
uv run --directory cloud/api arq mcp_audit_cloud.worker.WorkerSettings
pnpm --dir cloud/web dev
pnpm --dir cloud/web test && pnpm --dir cloud/web exec playwright test
```

## How to work in this repo

- **Phase order is strict.** Phases and exit gates are in ROADMAP. Do not start phase
  N+1 until phase N's gate passes and Srijith has ticked it in `PROGRESS.md`. If a
  gate fails, fix the engine — do not lower the gate.
- **Update `PROGRESS.md`** at the end of every session: what's done, what's next,
  open questions, any gate numbers measured. Keep it short.
- **One logical change per commit.** Conventional-style subjects (`engine: ...`,
  `cloud/api: ...`, `web: ...`). Branch per phase; PR into `main`.
- **Tests first for engine logic.** Differ/stats/features/sanitizer are pure
  functions — write the test table, then the code. Use the fake client pattern from
  `harness.py`'s self-check for anything touching the model.
- **Migrate the `if __name__ == "__main__"` self-checks into `tests/`** in Phase 0,
  then delete them from modules.
- **Explain why, not what,** in docstrings/comments — match the existing style.
- **Errors:** every user-facing failure is one readable line + a stable exit code
  (see ROADMAP §1.7). No raw `ExceptionGroup` tracebacks unless `--debug`.
- **Types:** `mypy --strict` on `src/mcp_audit`; `strict: true` in `tsconfig`.
  No `any` in the web app except at the JSON boundary, where you parse with zod.
- **Dependencies:** justify every new one in the PR description. Pin in lockfiles.

## Ask Srijith before you

- Change verdict thresholds, trial defaults, or the sanitizer's keep/strip lists.
- Run anything that spends real API money beyond ~$2 (live tests, bench runs).
- Add a paid feature, change plan limits/prices, or alter webhook → subscription logic.
- Publish anything: PyPI release, public benchmark results, naming a vulnerable server
  (responsible disclosure first — ROADMAP §2.4).
- Touch production infra, DNS, or secrets.

## Honest limits (keep these in the README; never claim otherwise)

Not caught: steering via tool/parameter **names** and `enum`/`const` values (they
survive sanitization by necessity); runtime output injection (tool *results* — we
never execute tools); rug-pulls between scans (Cloud monitoring narrows this, doesn't
close it); model-specific steering (a Haiku-clean server may steer another model).
