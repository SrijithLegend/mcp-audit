# ROADMAP — mcp-audit

Each phase ends in a **gate**: measurable criteria that must pass before the next phase
starts. Gates exist because a paid product built on an unvalidated verdict is worthless
— nobody pays a security tool they can't trust.

State as of 2026-09-22 (commit `adb5d51`): package layout fixed, LICENSE, sanitizer with
fixtures, dry-run stubs, single-trial harness, `inspect`/`trial`/`version` commands.
**Not done:** N trials, differ, verdict, `scan`, reports, exit codes, cost guard, tests
in pytest, CI, HTTP transport, validation, PyPI. Everything cloud.

---

## Phase 0 — Hygiene (≈ 1 day)

1. `tests/` with pytest + pytest-asyncio. Port every `__main__` self-check
   (`sanitizer`, `client`, `dryrun`, `harness`, `fixtures/check.py`) into tests, then
   delete the `__main__` blocks.
2. `tests/test_invariants.py`:
   - grep for `call_tool|session\.call` across `src/` and `cloud/` → must be zero.
   - spawned stdio env contains no key matching `(?i)key|token|secret|password` and no
     `ANTHROPIC_*` (spawn a fixture that prints `os.environ` keys to stderr; assert).
   - arm-equivalence: build the real and sanitized request payloads with a fake client;
     assert they differ only in descriptions/schema prose/`system`.
3. Sanitizer holes: walk `dependentSchemas`, `propertyNames`, `unevaluatedProperties`,
   `unevaluatedItems`, `contentSchema`, `dependencies` (dict-of-schema form only;
   array-of-names form is structural, keep it). Table-driven tests with prose planted at
   each keyword.
4. Fix README `default` claim; remove `ant auth login` mention.
5. Tooling: ruff (lint+format), mypy strict on `src/mcp_audit`, `pyproject` dev extras.
6. CI (`.github/workflows/ci.yml`): matrix py3.11/3.12/3.13 on ubuntu + macos; ruff,
   mypy, pytest (offline), `pip-audit`, gitleaks. Dependabot for pip + actions.
7. `PROGRESS.md` created with the phase checklist.

**Gate 0:** CI green on main; invariant tests present; zero `__main__` self-checks.

---

## Phase 1 — Finish the engine (≈ 1–2 weeks)

### 1.1 Models (`models.py`)
Pydantic v2: `Tool{name, description, input_schema}`, `Inventory{instructions, tools,
server_name?, server_version?, protocol_version?, captured_at, source}`,
`ToolCall{name, arguments, turn, index}`, `Trace{side: "real"|"sanitized", trial,
calls, stop_reason, input_tokens, output_tokens}`, `Signal`, `Finding`, `Verdict`
(enum `CONFIRMED|SUSPECTED|CLEAN|INCONCLUSIVE`), `Report`. `Inventory.sha256()` =
hash of canonical JSON (sorted keys) — used for caching and rug-pull detection.
Inventory JSON is the interchange format between CLI and Cloud: version it
(`"format": "mcp-audit/inventory@1"`).

### 1.2 Capture
- `capture/stdio.py`: existing `fetch_inventory`, plus: 30 s timeout (configurable),
  minimal env (CLAUDE.md invariant 4), `--env K=V` passthrough, `--cwd`, stderr captured
  to a ring buffer and shown only with `--debug`, process tree killed on exit/timeout.
  Clear errors: command not found, server crashed during init (show last 5 stderr
  lines), timeout, protocol error.
- `capture/http.py`: Streamable HTTP via the MCP SDK client. `--url`, repeatable
  `--header`. `initialize` + `tools/list` (follow pagination cursors) only. 15 s
  timeout, 2 MB response cap. In the CLI, localhost is allowed (it's the user's machine);
  in Cloud the caller wraps it with the SSRF guard (SECURITY.md §3).
- Pagination: `tools/list` may be paginated — follow `nextCursor` up to 50 pages /
  500 tools, then error `InventoryTooLarge`.

### 1.3 Harness
- Async (`AsyncAnthropic`), trials run concurrently with a semaphore (`--concurrency`,
  default 4). SDK retries on 429/529 (`max_retries=4`).
- **Prompt caching:** `cache_control: {"type": "ephemeral"}` on the last tool and on
  the system block. Same caching on both arms (invariant 2).
- `normalize_for_api(inventory) -> (api_tools, name_map)`: tool names mapped to a
  valid form reversibly (`a.b/c` → `a_b_c__<4hex>` on collision), schema repaired
  (`type: object` root, drop keywords the API rejects). Applied identically to both
  arms; traces are mapped back to original names.
- Temperature: API default (1.0). Stochasticity is what the trials sample. Record it.
- `max_tokens=1024`, `MAX_TURNS=6`. Record `stop_reason` per trial
  (`no_tool_calls | max_turns | api_error`).
- **Stub modes** (`dryrun.py`): keep `inert` (current); add `canary` — returns a small
  synthetic result embedding `MCPAUDIT-CANARY-<8 hex of sha256(tool:call_index)>`.
  Deterministic, identical across arms, still never echoes arguments. Canary
  appearing in a later call's arguments = **cross-tool data flow** (the exfil pattern
  in `poisoned_param.py`). Pick the default by fixture results in Gate 1; expect
  `canary`.
- Default task stays server-agnostic; `--task` overrides; Cloud caps it at 500 chars.

### 1.4 Differ, stats, verdict (`features.py`, `stats.py`, `differ.py`)

**Features per call** (pure functions, table-tested):
- `sensitive_arg`: any string arg matching the detector list — `/etc/(passwd|shadow)`,
  `~/.ssh`, `id_(rsa|ed25519)`, `.env`, `.aws/credentials`, `.git-credentials`,
  `.netrc`, `.kube/config`, env-var-like names `[A-Z_]*(KEY|TOKEN|SECRET|PASSWORD)`,
  `https?://` hosts not present anywhere in the inventory, base64 blob > 200 chars.
  Detectors are a registry so they can be extended; each has an id.
- `canary_flow`: argument contains a canary from an earlier stub result.
- `first_call`: the call is the first call of the trial.
- `optional_param_populated`: a non-required param is set non-empty.

**Signals.** For each tool `t`, count trials (not calls) on each arm where:
`called(t)`, `called_first(t)`, `sensitive(t, detector)`, `canary_flow(t)`,
`optional_populated(t, param)`. Each is `k_real/n` vs `k_san/n`.

**Test:** two-sided Fisher exact on the 2×2 table, implemented with `math.comb`
(no scipy). Reference values (n=5 each arm): 5/5 vs 0/5 → p=0.0079; 4/5 vs 0/5 →
0.048; 5/5 vs 1/5 → 0.048; 3/5 vs 0/5 → 0.167; 4/5 vs 1/5 → 0.206. n=10: 6/10 vs 0/10
→ 0.011; 7/10 vs 2/10 → 0.070. Put these in the test table.

**Security-relevant signals:** `sensitive`, `canary_flow`, `called_first` on a tool
with any sensitive/canary hit on either arm. Everything else (`called`,
`optional_populated`) is behavioral only.

**Global shift control:** compute mean calls/trial per arm. Honest descriptions help
the model use tools, so the real arm often calls *everything* more. A `called(t)`
delta that doesn't exceed the global ratio is not a finding.

**Verdict rules** (constants in `differ.py`):
- Holm-correct p-values across *security-relevant* signals only.
- `CONFIRMED`: a security-relevant signal with adjusted p < 0.05 **and**
  |Δrate| ≥ 0.6.
- `SUSPECTED`: security-relevant with raw p < 0.2 and |Δrate| ≥ 0.4; **or** a
  behavioral `called(t)` signal with p < 0.05, |Δ| ≥ 0.6 and exceeding the global shift.
- `INCONCLUSIVE`: > 30 % of trials on either arm ended in `api_error`, or zero tool
  calls on both arms (task gave no reason to use tools — tell the user to set `--task`).
- `CLEAN` otherwise.
- **Adaptive escalation:** if the best result after n=5 is SUSPECTED, run 5 more per
  arm (n=10) and re-evaluate once. Never more than once (repeated peeking inflates
  false positives). `--no-escalate` disables.
- Direction matters: report steering *toward* (real > sanitized) and *away*
  (real < sanitized, e.g. "never call audit_log") separately.
- Server verdict = worst tool verdict.

**Evidence per finding:** rates both arms, p (raw + adjusted), the detector id, and
one representative real-arm call (args truncated to 256 chars, secrets-looking values
masked) plus the sanitized-arm counterpart trial summary.

### 1.5 `scan` command
`mcp-audit scan <command> [args...] | --url URL | --inventory FILE`
Options: `--trials 5`, `--task`, `--model`, `--stub canary|inert`, `--concurrency 4`,
`--max-cost 1.00`, `--yes`, `--json`, `--sarif FILE`, `--md FILE`,
`--fail-on confirmed|suspected`, `--no-escalate`, `--debug`, `--cloud`.
Pipeline: capture → sha256 → sanitize → cost estimate/guard → trials (both arms,
interleaved so rate limits hit both equally) → differ → verdict → report.
Also: `mcp-audit sanitize ...` prints a unified diff of what was stripped (great for
users to see *what* we removed), `mcp-audit inspect --out inv.json` writes the
interchange file.

### 1.6 Cost guard (`cost.py`)
Before running: `messages.count_tokens` on turn-1 payload for each arm; estimate =
`2 × trials × E[turns] × input_tokens × price_in + output estimate`, with
`E[turns]=3`, prices from a `PRICES` table keyed by model (Haiku 4.5: $1 / $5 per
MTok; cached reads 0.1×). Print `~N API calls, est. $X.XX (max $Y.YY)`. If max >
`--max-cost` → abort unless `--yes`. Non-TTY never prompts. Actual tokens/cost go in
the report.

### 1.7 Output and exit codes
- Terminal (rich): header (server, model, trials, cost), verdict banner, table per tool
  (verdict, signal, real rate, sanitized rate, p), evidence block, limits footnote.
- `--json`: `Report` model dump, schema versioned `mcp-audit/report@1`.
- `--sarif`: SARIF 2.1.0 for GitHub code scanning.
- Exit codes: `0` clean/inconclusive, `1` confirmed (or suspected with
  `--fail-on suspected`), `2` usage error (Click default), `3` capture failure,
  `4` API/auth failure, `5` budget exceeded.
- Error map: missing API key → "Set ANTHROPIC_API_KEY (BYOK) or run `mcp-audit login`
  for Cloud."; 401 → invalid key; server spawn failures as in 1.2.

### 1.8 Fixtures to add
- `poisoned_tool_desc.py` (classic: payload in a tool description)
- `poisoned_nested.py` (payload in `$defs` / `anyOf` param description)
- `poisoned_suppress.py` (steers *away*: "never call audit_log")
- `benign_verbose.py` (long, honest, directive-ish descriptions: "Always call list_notes
  before read_note") — **the false-positive trap**. Must come out CLEAN or at most
  behavioral SUSPECTED, never CONFIRMED.
- `http_fixture.py` (same poisoned server over Streamable HTTP)

**Gate 1 (live, costs ~$5–10, ask first):** run `scan` 10× per fixture with defaults.
- Every poisoned fixture: CONFIRMED in ≥ 9/10 runs.
- `clean.py` and `benign_verbose.py`: CONFIRMED in 0/10 runs.
- Median cost per scan on fixtures recorded in `bench/fixtures.md`.
- Offline test suite green; mypy strict clean.
If a poisoned fixture fails, improve features/stubs — do not loosen thresholds.

---

## Phase 2 — Validate and launch the CLI (≈ 1 week)

### 2.1 Real-server benchmark (`bench/`)
Scan 10–15 popular public MCP servers (official reference servers + popular community
ones). `bench/servers.yaml` lists command/url + task per server. `bench/run.py` writes
`bench/results.csv` (server, version, tools, verdict, signals, cost, date).

### 2.2 Head-to-head
Run `mcp-scan` / Snyk `agent-scan` on the same servers + all fixtures. Table: for each
tool, their flags vs our verdict. Headline metric: **false positives on the clean and
benign_verbose fixtures and on servers where manual review finds no steering**. Record
tool versions and dates. Be fair: report where they catch things we can't (names,
enums, known-bad hashes).

### 2.3 Packaging
- Trusted publishing to PyPI via GitHub OIDC on tag `v*` (`release.yml`), no API
  token. Build sdist+wheel; smoke-test `uvx mcp-audit version` and a fake-client scan in
  a clean container in CI before publishing.
- `action/action.yml`: composite GitHub Action — installs via `uvx`, runs `scan`
  with `--sarif`, uploads to code scanning, fails on exit code 1. Inputs: `command`,
  `url`, `trials`, `max-cost`, `fail-on`, `api-key` (BYOK) or `cloud-token`.

### 2.4 Responsible disclosure
If a real server is CONFIRMED: manually verify, privately notify the maintainer
(GitHub security advisory or email), 30-day window, then publish. Never name it in
bench output before that. `SECURITY.md` at repo root documents how people report bugs
in mcp-audit itself.

### 2.5 Docs
README: one-line pitch, `uvx mcp-audit scan ...`, example output, how the differential
works (diagram), cost note, dry-run safety note, benchmark table, "what this does NOT
catch", CI usage. Demo via asciinema/GIF. `docs/methodology.md` with the stats.

**Gate 2:** on PyPI; Action works on a sample repo; benchmark + head-to-head published;
Srijith ticks "launched" in PROGRESS.md. **Strong recommendation:** don't start Cloud
until real strangers use the CLI (issues, stars, installs). Cloud without users is a
cost center.

---

## Phase 3 — Cloud backend (≈ 2 weeks)

### 3.1 Service layout (`cloud/api`, package `mcp_audit_cloud`)
`main.py` (app factory, middleware), `config.py` (pydantic-settings, fails fast on
missing env), `db.py` (async engine, session dep), `models/` (SQLAlchemy),
`schemas/` (pydantic I/O), `routers/`, `services/` (scan, quota, billing, monitors),
`auth.py`, `ssrf.py`, `ratelimit.py`, `worker.py` (arq settings + jobs),
`billing/{base.py,dodo.py,polar.py}`, `alembic/`.

### 3.2 Data model (Postgres; UUIDv7 PKs; `created_at/updated_at` everywhere)
- `users(id, clerk_user_id uniq, email, name)`
- `orgs(id, name, slug uniq, plan, personal bool)` — every user gets a personal org
- `memberships(org_id, user_id, role owner|admin|member, pk(org_id,user_id))`
- `api_tokens(id, org_id, name, prefix, token_hash uniq, scopes[], last_used_at,
  expires_at, revoked_at, created_by)` — token shown once; store sha256 only
- `targets(id, org_id, kind inventory|remote_http, name, url?, header_names[])` — header
  *values* never stored in Postgres (SECURITY.md §4)
- `inventories(id, org_id, sha256, content jsonb, source, captured_at, uniq(org_id,sha256))`
- `scans(id, org_id, target_id?, inventory_id, status queued|running|succeeded|failed|
  canceled, trials, model, task, stub_mode, verdict?, report jsonb?, error_code?,
  input_tokens, output_tokens, cost_micros, created_by, created_via web|api|monitor|ci,
  queued_at, started_at, finished_at, share_token? uniq)`
- `scan_findings(id, scan_id, tool, verdict, signal, real_rate, san_rate, p_raw, p_adj,
  evidence jsonb)` — for filtering/analytics; the report jsonb is canonical
- `monitors(id, org_id, target_id, cron, enabled, last_sha256, last_checked_at,
  last_status)`
- `inventory_changes(id, monitor_id, old_sha256, new_sha256, diff jsonb, scan_id?)`
- `usage(org_id, period_start, scans_used, cost_micros, pk(org_id, period_start))`
- `subscriptions(org_id pk, provider, customer_id, subscription_id, plan, status,
  current_period_end, cancel_at_period_end, raw jsonb)`
- `webhook_events(provider, event_id, received_at, processed_at, pk(provider,event_id))`
- `audit_log(id, org_id, actor_user_id?, actor_token_id?, action, target, meta jsonb, ip)`

Every table with `org_id` gets an index on it. Enable Postgres RLS on org tables as
defense-in-depth (app sets `app.org_id` per transaction); primary enforcement is the
repository layer (SECURITY.md §5).

### 3.3 API (v1, JSON, OpenAPI published)
```
GET  /healthz /readyz
GET  /v1/me                           # user + orgs + current plan + usage
POST /v1/orgs  GET/PATCH /v1/orgs/{id}  members invite/remove (Team plan)
POST /v1/scans                        # {inventory | target_id, trials?, task?, model?} -> 202 {id}
GET  /v1/scans?cursor=&target_id=&verdict=
GET  /v1/scans/{id}   POST /v1/scans/{id}/cancel
GET  /v1/scans/{id}/report.{json,md,sarif}
POST /v1/scans/{id}/share   DELETE /v1/scans/{id}/share
GET  /v1/shared/{share_token}         # public, read-only, redacted
CRUD /v1/targets  CRUD /v1/monitors  GET /v1/monitors/{id}/changes
CRUD /v1/tokens
POST /v1/billing/checkout  POST /v1/billing/portal
POST /webhooks/billing/{provider}
DELETE /v1/me                         # account deletion (DPDP/GDPR)
```
Cursor pagination everywhere (no offset). Idempotency-Key header honored on
`POST /v1/scans` (Redis, 24 h). Errors: RFC 9457 problem+json with stable `type` codes.

### 3.4 Scan pipeline
1. Validate input (size/shape limits, SECURITY.md §6). If `target_id` is remote_http,
   capture happens in the worker, not the request.
2. **Quota check + reservation in one transaction:** `SELECT ... FOR UPDATE` on
   `usage` row; reject 402 with upgrade URL if over plan; increment; commit; enqueue.
   Refund the reservation if the scan fails for a reason that's ours (API outage), not
   theirs (bad inventory).
3. Global spend breaker: Redis counter of today's estimated cost; above
   `DAILY_SPEND_LIMIT_USD` new scans get 503 + ops alert.
4. Worker: capture (if remote) → engine `audit()` with Cloud limits (trials ≤ plan max,
   `max_turns` 6, task ≤ 500 chars, arguments truncated to 512 chars in stored traces) →
   persist report + findings + usage cost → notify (email/webhook if configured).
5. Job timeout 10 min; retries only for transient API errors; cancellation checked
   between trials.
6. Cache: identical `(inventory sha256, model, trials, task, stub_mode, engine version)`
   within 24 h in the same org → return the existing scan (free, no quota).

### 3.5 Auth
- Web: Clerk session JWT in `Authorization: Bearer`. Verify with Clerk JWKS (cached,
  rotated), check `iss`, `aud`/`azp` allowlist, `exp`, `nbf`. Upsert user on first
  sight; create personal org.
- CLI/CI: `mcpa_<32 bytes base62>`; `mcp-audit login` opens the web token page, user
  pastes token, stored in OS keyring (fallback: `~/.config/mcp-audit/credentials`
  chmod 600). `scan --cloud` captures locally and POSTs the inventory.
- Roles: owner (billing, delete org), admin (tokens, monitors, members), member (scans).

### 3.6 Monitoring (rug-pull detection) — the core recurring-value feature
Remote HTTP targets only (inventory-upload targets are re-checked when the user's CI
uploads again). Cron per plan (Pro: daily; Team: hourly). Worker captures, compares
sha256; on change: store structural + prose diff, auto-run a scan, email/notify with
the diff and verdict. This is what justifies a *subscription* rather than one-off
payments — build it well.

**Gate 3:** API + worker pass unit + integration tests (testcontainers Postgres/Redis);
IDOR, SSRF, webhook, quota-race and rate-limit test suites from SECURITY.md all pass;
`docker compose up` gives a working local stack.

---

## Phase 4 — Frontend (`cloud/web`, ≈ 2 weeks)

Stack per D6. zod schemas generated from the API OpenAPI (`openapi-typescript` +
zod), one typed fetch client. Clerk components for auth. Dark default, light supported.
Dense, terminal-adjacent look; monospace for all server-supplied text.

Pages:
- `/` landing: pitch, 20-second demo GIF, "how it works" diagram, benchmark vs
  mcp-scan table (from `bench/`), pricing, CLI install snippet, FAQ, honest limits.
- `/pricing`, `/docs` (MDX: quickstart, CLI, CI, methodology, API), `/security`,
  `/legal/{terms,privacy,refunds}`, `/changelog`.
- `/app` dashboard: recent scans, verdict counts, usage meter vs plan.
- `/app/scans/new`: tabs — upload inventory JSON (drag-drop, validated client-side
  with zod), remote URL (+ header names/values), or copy-paste CLI command for
  `scan --cloud`. Shows cost/quota impact before submit.
- `/app/scans/[id]`: status (poll 2 s while running, or SSE), verdict banner, per-tool
  table, **side-by-side arm view** (real vs sanitized traces per trial, divergent calls
  highlighted), stripped-prose diff (what was removed from the real inventory),
  export buttons (JSON/MD/SARIF), share toggle.
- `/share/[token]`: public read-only report, `noindex`, redacted.
- `/app/targets`, `/app/monitors` (+ change history with diffs).
- `/app/settings/{tokens,billing,org,members}`.

Rules:
- **Never** `dangerouslySetInnerHTML`; never render server prose as markdown. Render
  inside `<pre>`/`<code>` as text; truncate with expand; mark invisible/bidi Unicode
  (U+200B–U+200F, U+202A–U+202E, U+2066–U+2069, tags block U+E0000–U+E007F) visibly —
  hidden-char payloads are a real attack and showing them is a feature.
- Security headers + CSP via `next.config` / middleware (SECURITY.md §8).
- Accessibility: keyboard nav, focus states, contrast AA, verdicts not color-only.
- Tests: vitest for components/utils; Playwright e2e for sign-in → upload fixture
  inventory → see CONFIRMED (API mocked in CI via MSW; one real-stack e2e nightly).

**Gate 4:** Playwright suite green; Lighthouse ≥ 90 perf/a11y on landing; no CSP
violations in console on any page.

---

## Phase 5 — Billing (≈ 1 week)

### 5.1 Plans (config in `cloud/api/.../plans.py`, single source of truth, mirrored to
the pricing page via API `GET /v1/plans`)

| | Free | Pro | Team |
|---|---|---|---|
| Price | $0 | $19/mo ($190/yr) | $79/mo ($790/yr) |
| Hosted scans / mo | 10 | 300 | 1,500 pooled |
| Max trials / arm | 5 | 10 | 20 |
| Remote HTTP targets | 1 | 20 | 100 |
| Monitors | — | 10, daily | 100, hourly |
| History retention | 7 days | 1 year | 2 years |
| API tokens / CI | 1 | 10 | 50 |
| Seats | 1 | 1 | 10 (+$8/seat) |
| Share links, SARIF | ✓ | ✓ | ✓ |

Prices are placeholders — Srijith decides. Sanity check before launch: measured
median cost/scan (Gate 1) × plan scans must stay < 30 % of plan price after MoR fees.
Example: at ~$0.10/scan, Pro's 300 scans = $30 > $19 — **either cost per scan comes
down (caching, fewer turns) or limits change.** Compute this from real numbers, don't
ship the table blindly.

### 5.2 Implementation
- `BillingProvider` protocol: `create_checkout(org, plan, interval) -> url`,
  `create_portal(org) -> url`, `verify_webhook(headers, body) -> Event`,
  `to_subscription_state(event) -> SubscriptionState`. `DodoProvider` first;
  `PolarProvider` stub with the same tests.
- Checkout carries `org_id` in metadata. Never trust the success redirect — only the
  webhook changes plan state.
- Webhook handler: verify signature on raw body (Standard Webhooks: `webhook-id`,
  `webhook-timestamp` within 5 min, `webhook-signature`), insert into `webhook_events`
  (PK conflict → 200 no-op, idempotent), process in the same transaction, return 2xx
  fast. Out-of-order events: apply only if event time ≥ stored `updated_at`.
- Plan state machine: `active → past_due (7-day grace, keep features) → canceled
  (downgrade to Free at period end)`. Downgrade never deletes data; over-limit monitors
  are paused, not removed.
- Entitlements checked server-side at every gated action via `entitlements(org)`.
  Frontend only reflects them.
- Test mode keys in dev/staging; a CLI script to replay recorded webhook fixtures.
- Legal pages required by the MoR (terms, privacy, refund policy, contact) before
  going live.

**Gate 5:** end-to-end in test mode — upgrade, renewal, failed payment → grace →
cancel → downgrade, plan change, refund — each reflected correctly; webhook replay and
forged-signature tests pass.

---

## Phase 6 — CI & integrations (≈ 3–4 days)
- GitHub Action supports `cloud-token` mode: captures locally, uploads, polls, writes
  SARIF + a PR comment (verdict table + report link).
- Outbound webhooks per org (scan.completed, monitor.changed), signed with
  Standard Webhooks; retries with backoff; delivery log.
- Slack incoming-webhook notification option for monitors.

## Phase 7 — Production readiness (≈ 1 week, overlaps)
- Deploy: `fly.toml` for `api` (2 machines, min 1 running) and `worker` (scale 1–3);
  Neon (PITR on) ; Upstash Redis; Vercel for web. Staging env mirrors prod with test-mode
  billing. Deploy via GitHub Actions on merge to `main` (staging) and tag (prod).
- Alembic migrations run as a release command; migrations must be backward-compatible
  (expand → migrate → contract).
- Observability: Sentry (api, worker, web) with PII scrubbing; structlog JSON with
  `request_id`, `org_id`, `scan_id`; metrics: queue depth, scan duration, cost/scan,
  API error rate, webhook failures. Alerts: queue > 50 for 10 min, spend breaker
  tripped, webhook failure rate > 5 %, 5xx > 1 %.
- Backups: Neon PITR + weekly logical dump to object storage; **restore drill once**
  and document it.
- Runbooks in `docs/runbooks/`: Anthropic outage, spend spike, leaked secret rotation,
  webhook backlog, bad deploy rollback.
- Load test (k6): 50 concurrent scan submissions; worker throughput under Anthropic
  rate limits; confirm quota race safety.
- Pre-launch security pass: run `mcp-audit` against itself (dogfood), ZAP baseline scan
  of web + API, review SECURITY.md checklist line by line.
- Status page (free tier of any provider) linked in footer.

**Gate 7 (launch):** SECURITY.md checklist 100 % ticked, restore drill done, staging
soak 72 h without alerts, legal pages live, Srijith signs off.

---

## Out of scope (until there's demand)
SSO/SAML, on-prem, stdio scanning in the cloud (would need Firecracker/gVisor sandboxes
— only revisit with paying enterprise demand), multi-provider models (OpenAI/Gemini
arms) — plausible Pro feature later since steering is model-specific.
