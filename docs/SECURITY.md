# SECURITY — threat model and required controls

A security tool that gets owned is worse than no tool. Every control below has a test
or a checklist item. Section numbers are referenced from CLAUDE.md and ROADMAP.md.

## 1. Assets and adversaries

**Assets:** our Anthropic API key and spend; customer scan reports (they reveal what
MCP servers a company runs and which are vulnerable); remote-server auth headers;
API tokens; billing state; the integrity of verdicts.

**Adversaries:**
- A malicious MCP server author (controls every string in the inventory, and for
  remote targets controls the HTTP responses).
- A malicious Cloud user (tries to get code execution, SSRF, other orgs' data, free
  LLM usage, or billing bypass).
- A network attacker (webhooks, token theft).
- Supply chain (compromised PyPI/npm dependency, compromised GitHub Action).

## 2. Code execution — the CLI runs servers, the Cloud never does

- CLI: `inspect`/`scan <command>` executes the user's command on the user's machine.
  That's the user's choice; the README and `--help` say so plainly ("this runs the
  server locally; only scan servers you'd be willing to run").
- CLI spawn env is an allowlist (CLAUDE.md invariant 4). Test with a fixture that dumps
  its env.
- Cloud accepts only inventory JSON or `https://` URLs. There is no code path that
  spawns a process from user input in `cloud/`. `tests/test_invariants.py` greps
  `cloud/` for `subprocess`, `os.system`, `asyncio.create_subprocess`, `stdio_client`,
  `StdioServerParameters` — must be zero.
- Tool execution never happens anywhere (invariant 1).

## 3. SSRF guard for remote targets (`cloud/api/.../ssrf.py`)

Remote-target fetching is the Cloud's biggest attack surface. Required:
- Scheme `https` only; port 443 only (allow 8443 behind a flag if users need it).
- Resolve hostname once; reject if **any** resolved address is private, loopback,
  link-local, multicast, reserved, CGNAT (100.64/10), unique-local (fc00::/7),
  IPv4-mapped IPv6 of any of those, or cloud metadata (169.254.169.254,
  fd00:ec2::254). Use `ipaddress` properties + explicit list.
- **Pin the connection to the validated IP** (custom httpx transport that connects to
  the IP and sends the original Host/SNI) — defeats DNS rebinding.
- No redirects (`follow_redirects=False`); a redirect is an error.
- Timeouts: connect 5 s, total 15 s. Response cap 2 MB streamed; abort beyond.
- Only `initialize`, `notifications/initialized`, `tools/list` are ever sent.
- Workers' egress in production goes through an egress proxy (e.g. smokescreen) that
  independently denies private ranges — second wall if the app check has a bug.
- Test table: `http://`, `https://127.0.0.1`, `https://[::1]`, `https://localhost`,
  `https://169.254.169.254`, decimal/octal IPs (`https://2130706433`), `0.0.0.0`,
  IPv4-mapped v6, a DNS name resolving to private, rebinding (first public then
  private), 301 to internal, oversized body, slowloris body.

## 4. Secrets

- Our secrets: only in platform secret stores (Fly secrets, Vercel env). Loaded via
  pydantic-settings; app refuses to start if any required secret is missing.
  `.env*` in `.gitignore`; gitleaks in CI and as a pre-commit hook.
- Remote-target auth headers: values held only in Redis, encrypted with
  AES-GCM (key from `HEADER_ENC_KEY` secret), TTL 1 h for one-off scans. Monitors need
  them long-term → stored encrypted in a separate `target_secrets` table with the key
  outside the DB; header *names* only in `targets`. Never logged, never returned by
  the API after creation (write-only fields), never included in reports.
- API tokens: generated with `secrets.token_bytes(32)`, shown once, stored as
  sha256; lookup by hash; constant-time compare; `last_used_at` updated async.
  Revocation takes effect immediately.
- Anthropic key: server-side only, workers only (API process doesn't need it except for
  `count_tokens` — prefer doing estimation in the worker too). Per-environment keys with
  Anthropic-console spend limits set as the outermost breaker.
- Log redaction: structlog processor masks `authorization`, `cookie`, `x-api-key`,
  `mcpa_*`, `sk-ant-*`, and any key containing `token|secret|password|key`.

## 5. AuthN / AuthZ

- Every org-scoped query goes through a repository helper requiring `org_id` from the
  authenticated principal. Never accept `org_id` from the body for authorization.
- Postgres RLS on org tables as a second wall (policy on `current_setting('app.org_id')`).
- IDOR test suite: two orgs, every endpoint with an ID param, cross-org access must
  return 404 (not 403 — don't leak existence). Generated from the OpenAPI route list so
  new routes are covered automatically.
- Share tokens: 32 bytes random, revocable, reports served redacted (no task text, no
  target URL, no header names, args truncated), `X-Robots-Tag: noindex`.
- Role checks on billing (owner), tokens/monitors (admin+).
- Clerk JWT verification per ROADMAP §3.5; reject tokens without expected `azp`.

## 6. Input validation and abuse

- Inventory upload: ≤ 2 MB body, ≤ 500 tools, schema nesting depth ≤ 32, any string
  ≤ 64 KB, total ≤ 5,000 schema nodes; validated by pydantic *before* storage.
  JSON parsed with size cap at the ASGI layer (reject by `Content-Length` and by
  streamed count).
- Task text ≤ 500 chars. Trials bounded by plan. `max_turns` fixed server-side.
- **LLM-proxy abuse:** an attacker could use custom tasks + tool args to extract free
  model output. Mitigations: stored/returned args truncated to 512 chars, no assistant
  text is ever returned, per-org quota, per-IP signup throttling, Free-plan task is the
  default task only (custom task = Pro+).
- Rate limits (Redis sliding window): unauthenticated 30 req/min/IP; authenticated
  300 req/min/org; scan creation 10/min/org; token creation 10/hour/org; shared report
  views 60/min/IP.
- Quota race: reservation under `SELECT … FOR UPDATE` (ROADMAP §3.4); test with 50
  concurrent submissions against a quota of 10 → exactly 10 accepted.
- Global daily spend breaker (ROADMAP §3.4).

## 7. Webhooks (inbound billing, outbound customer)

- Inbound: verify signature over the **raw** body before parsing; timestamp tolerance
  5 min; idempotency table; constant-time compare; reject unknown event types with 2xx
  (so provider doesn't retry forever) but log. Tests: forged signature, replayed id,
  stale timestamp, out-of-order events.
- Outbound: signed (Standard Webhooks), destination URLs pass the same SSRF guard
  (§3), no redirects, 5 s timeout, retries with backoff, payload contains scan id +
  verdict + link, never full traces.

## 8. Web app

- CSP: `default-src 'self'; script-src 'self' 'nonce-…' https://*.clerk.accounts.dev
  <clerk frontend api>; connect-src 'self' <api origin> <clerk>; img-src 'self' data:
  <clerk img>; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action
  'self'`. Adjust Clerk/Dodo hosts from their docs; no `unsafe-inline` scripts.
- HSTS (preload-ready), `X-Content-Type-Options: nosniff`, `Referrer-Policy:
  strict-origin-when-cross-origin`, `Permissions-Policy` minimal.
- API CORS: exact allowlist of web origins; no credentials mode (bearer tokens).
- Server-supplied text rendering rules: ROADMAP Phase 4 (no HTML/markdown, show hidden
  Unicode). Exports: markdown reports escape backticks/pipes; CSV exports prefix cells
  starting with `= + - @` with `'` (formula injection).
- Dependencies: `pnpm audit` in CI, lockfile committed, Renovate/Dependabot.

## 9. Infrastructure and supply chain

- Containers: slim/distroless base pinned by digest, non-root user, read-only root FS,
  no shell in prod image if feasible. Workers have no inbound ports.
- GitHub Actions: pin third-party actions by commit SHA; `permissions:` least privilege
  per workflow; PyPI via trusted publishing (OIDC); branch protection on `main`
  (PR + green CI required).
- CodeQL for Python + TS; `pip-audit`; gitleaks; Dependabot.
- Our own GitHub Action (`action/`) runs with `contents: read`, `security-events: write`
  only; the cloud token is a masked secret input.

## 10. Privacy and data lifecycle

- Retention per plan; nightly job hard-deletes expired scans/traces.
- Account deletion deletes org data (if sole owner) within 24 h; billing records kept as
  the MoR/law requires.
- Privacy policy covers: what we store (inventories, traces, emails), sub-processors
  (Anthropic, Clerk, Dodo, Neon, Upstash, Fly, Vercel, Sentry, Resend), India DPDP Act
  and GDPR basics, contact for data requests.
- Inventories may contain customer-internal tool names — treat as confidential; never
  used for marketing/benchmarks without explicit opt-in.

## Launch checklist (copy into PROGRESS.md, tick each with the test/PR that proves it)

- [ ] No-tool-execution grep invariant (src + cloud)
- [ ] No-subprocess invariant (cloud)
- [ ] Spawn env allowlist test
- [ ] SSRF test table (§3) all rejected; egress proxy configured
- [ ] Header values encrypted, write-only, redacted in logs
- [ ] API tokens hashed, shown once, revocation immediate
- [ ] IDOR suite generated from OpenAPI, all 404
- [ ] RLS enabled + tested
- [ ] Input limits enforced at ASGI + pydantic
- [ ] Rate limits + quota race test
- [ ] Daily spend breaker + Anthropic console limit
- [ ] Webhook signature/replay/out-of-order tests
- [ ] CSP/HSTS/headers verified in prod (securityheaders.com A)
- [ ] Hidden-Unicode rendering + no HTML rendering of server text
- [ ] Log redaction test
- [ ] Actions pinned by SHA, least-privilege permissions, trusted publishing
- [ ] CodeQL / pip-audit / pnpm audit / gitleaks green
- [ ] Backups + restore drill done
- [ ] Privacy, terms, refund pages live
- [ ] `/.well-known/security.txt` + root `SECURITY.md` disclosure policy
