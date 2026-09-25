# PROGRESS

Claude Code: update this at the end of every session. **Srijith ticks the gates** — a gate
is a measurement, and nothing here has been measured against a live model yet.

## Current phase: 1 → 2 (engine built; Gate 1 not run)

Everything through Phase 7 is **implemented**. What is missing is the part that costs money
and needs a human: the live fixture gate, the real-server benchmark, the head-to-head, and
publishing. Those are the gates, and they are why the phase above says 1 and not 7.

## Gates

- [x] **Gate 0** — invariant tests present, zero `__main__` self-checks, ruff + mypy strict
      clean, CI workflows written. *(CI has not run on GitHub yet — no push.)*
- [ ] **Gate 1** — fixtures live: poisoned ≥ 9/10 CONFIRMED, `clean` + `benign_verbose`
      0/10. `uv run pytest -q -m gate` (~$5–10, **needs your go-ahead and a key**).
- [ ] **Gate 2** — PyPI + Action + benchmark + head-to-head published; launched.
- [x] **Gate 3 (code)** — API + worker + security suites: SSRF table, IDOR, quota race, RLS,
      webhook forgery/replay/ordering, rate limits, spend breaker. 131 tests pass.
      *Not ticked as done:* `docker compose up` has not been run here (no Docker in this
      environment), so the Postgres-only tests are verified by construction and by CI
      config, not by a local run.
- [ ] **Gate 4** — Playwright suite green. Specs written and wired; the browser binary could
      not be downloaded here (CDN timeouts), so **they have never executed**. Lighthouse not
      run either.
- [ ] **Gate 5** — billing lifecycle in test mode. Code + replay script + 18 unit tests done;
      needs real Dodo test-mode keys and product ids.
- [ ] **Gate 7** — launch checklist (docs/SECURITY.md) 100%, restore drill done, 72h soak.

## Done

Phase 0 — `CLAUDE.md` replaces `claude.md`, docs under `docs/`, root `SECURITY.md` is the
disclosure policy, ruff + mypy strict + pytest with `live`/`gate` markers deselected,
CI/CodeQL/Dependabot, README corrections (`default` is stripped; no `ant auth login`; the
cost formula is per-trial).

Phase 1 — the engine. `models` (versioned Inventory/Report wire formats), `capture/`
(stdio with an env allowlist; Streamable HTTP with no redirects and a 2 MB cap; pagination),
`harness` (async, concurrent, cache breakpoints, reversible tool-name normalisation),
`dryrun` canary mode, `features`/`stats`/`differ` (Fisher exact via `math.comb`, Holm over
security-relevant signals, global-shift control, one round of adaptive escalation), `cost`
(count_tokens + hard ceiling), `report/` (terminal, JSON, Markdown, SARIF), `cli`
(inspect/sanitize/scan/trial/login), 8 fixtures. **180 offline tests.**

Phase 2 — `bench/run.py` (spend ceiling, anonymised by default), `bench/headtohead.py`
(false positives on manually-clean servers is the headline column), composite GitHub Action
with the body in `scan.sh` so no user string is interpolated by the templater, release
workflow with trusted publishing and a clean-container smoke test, `docs/methodology.md`.

Phase 3 — `cloud/api`: FastAPI + SQLAlchemy 2 async + Alembic + arq. SSRF guard with
IP pinning, Clerk JWT + `mcpa_` tokens, org-scoped repository layer with RLS behind it,
AES-GCM header storage, atomic quota reservation, spend breaker that fails closed,
retention sweep, monitors with structural/prose diffs. **131 tests.**

Phase 4 — `cloud/web`: Next.js 16 App Router, 21 routes, one renderer for hostile text that
shows invisible characters instead of hiding them, zod at the JSON boundary, per-request CSP
nonce, side-by-side arm view. **61 vitest tests**, Playwright specs written.

Unit economics (2026-09-25) — hosted scanning is bounded in **dollars**, not scan counts.
Three leaks closed: `usage.cost_micros` was recorded and never read; the worker used the
global per-scan ceiling instead of the plan's (so a Free scan could cost 10× what Free
says); and monitor auto-scans bypassed quota entirely (~300 free scans/month at ten daily
monitors). `tests/test_economics.py` (16 tests) proves the bound holds even when every scan
costs its maximum.

Phases 5–7 — billing behind `BillingProvider` (Dodo + Polar, Standard Webhooks, plan state
machine with a 7-day grace), webhook replay script, `scan --cloud`, org outbound webhooks +
Slack, cloud CI with Postgres/Redis services and a migration up/down/up check, deploy
workflow (staging on main, production on tag), 6 runbooks, k6 quota-race load test,
`metrics.py` with the alert rules written down where they can be reviewed.

## Next, in order

1. **Gate 1.** Set `ANTHROPIC_API_KEY`, then `uv run pytest -q -m gate`. Fill in
   `bench/fixtures.md` with CONFIRMED counts and the **median cost per scan**, then put that
   number in `plans.ESTIMATED_COST_PER_SCAN_USD`. It changes how many scans each plan
   advertises; it cannot change the margin.
2. Push and let CI run. Fix whatever only a real runner finds.
3. `npx playwright install chromium` then `npm run e2e` in `cloud/web` for Gate 4.
4. `docker compose -f cloud/infra/docker-compose.yml up -d` and
   `uv run --directory cloud/api pytest -q -m db` for the Postgres-only tests.
5. Then Phase 2 for real: `bench/run.py --dry-run` first, then a budgeted live run, then the
   head-to-head. Disclosure before any server is named.

## Measured numbers

| What | Value | When |
|---|---|---|
| Offline tests (engine / cloud API / web) | 180 / 158 / 61 | 2026-09-25 |
| Fixture gate (poisoned CONFIRMED rate) | not measured | — |
| Control fixtures (false positive rate) | not measured | — |
| Median cost per scan | not measured (assumed $0.06, pessimistic) | — |
| Worst-case margin, Pro / Team | $12.86 / $52.26 guaranteed | 2026-09-25 |
| Max monthly exposure (all orgs) | ~$750 (daily breaker × 30) | 2026-09-25 |
| Real-server benchmark | not run | — |

## Open questions for Srijith

- ~~**Plan prices.**~~ **Resolved differently.** Plans now include *dollars of model time*
  and the scan count is derived from that, so the margin no longer depends on the cost
  estimate being right: Pro keeps $12.86 and Team $52.26 even if a customer spends every
  included dollar. Gate 1 now only decides how many scans a budget buys — it cannot make
  the service unprofitable. **What still needs your sign-off:** the budgets themselves
  ($0.30 / $5 / $22, i.e. 30 % of net revenue) and the fact that the advertised scan counts
  fell out at 5 / 83 / 366 because `ESTIMATED_COST_PER_SCAN_USD` is a pessimistic $0.06.
  One constant to change in `plans.py` once Gate 1 measures the real number.
- **`poisoned_suppress.py` and the gate.** Suppressing an audit tool is steering *away* from
  a call, and by the current rules that is behavioural, so it can legitimately land on
  SUSPECTED rather than CONFIRMED. Either suppression of an audit-shaped tool becomes
  security-relevant (a threshold change, which needs you) or that fixture's gate is
  SUSPECTED. Flagged in `bench/fixtures.md`.
- **`cloud/` license** — AGPL in this repo as committed (D7), or move it to a private one.
- **shadcn/ui** — components are written in its shape but the registry is not vendored.
  Partial deviation from D6; say if you want the real thing.
