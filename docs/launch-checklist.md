# Launch checklist (Gate 7)

The checklist from `docs/SECURITY.md`, with the test or file that proves each line. A tick
means **verified**, not **written** — several lines below are implemented and honestly
unticked because they have never been run against real infrastructure.

| # | Control | Proof | Status |
|---|---|---|---|
| 1 | No tool execution anywhere (`src/` + `cloud/`) | `tests/test_invariants.py::test_no_live_tool_execution_anywhere` | ✅ |
| 2 | No subprocess in `cloud/` | `tests/test_invariants.py::test_cloud_never_spawns_processes` | ✅ |
| 3 | Spawn env allowlist | `test_invariants.py::test_env_allowlist_is_what_the_server_actually_sees` (spawns `fixtures/env_dump.py`) | ✅ |
| 4 | Arms differ only in prose | `test_invariants.py::test_arms_differ_only_in_prose` | ✅ |
| 5 | SSRF table all rejected | `cloud/api/tests/test_ssrf.py` — 29 rejection rows + rebinding + caps | ✅ |
| 6 | Connection pinned to the validated IP | `test_ssrf.py::test_the_connection_is_pinned_to_the_validated_address` | ✅ |
| 7 | Egress proxy denies private ranges independently | `cloud/infra/fly.worker.toml` (`HTTPS_PROXY`) | ⬜ needs the proxy deployed |
| 8 | Header values encrypted, write-only, redacted | `test_services.py` (AAD binding, nonce reuse) + `test_api.py::test_target_header_values_are_never_returned` | ✅ |
| 9 | API tokens hashed, shown once, revocation immediate | `test_api.py::test_token_is_shown_once_and_works_then_revokes` | ✅ |
| 10 | IDOR: cross-org is 404 | `test_api.py::test_cross_org_access_is_404_not_403`, `..._not_in_my_list` | ✅ |
| 11 | RLS enabled and tested | policies in `alembic/versions/..._initial.py`; `test_api.py` marked `db` | ⬜ needs a Postgres run |
| 12 | Input limits at ASGI + pydantic | `main.py` body cap + `test_services.py` (tools, depth, nodes, strings, task) | ✅ |
| 13 | Rate limits + quota race | `test_services.py` limiter tests + `test_api.py::test_the_quota_race_accepts_exactly_the_limit` | ⬜ race test needs Postgres |
| 14 | Daily spend breaker, fails closed | `test_services.py::test_the_breaker_fails_closed_when_redis_is_down` | ✅ |
| 15 | Anthropic console spend limit set | outside the repo | ⬜ |
| 16 | Webhook signature / replay / stale / out-of-order | `cloud/api/tests/test_billing.py` (18 tests) + `scripts/replay_webhook.py` | ✅ code, ⬜ against real test-mode keys |
| 17 | CSP / HSTS / headers | `middleware.ts`, `next.config.ts`, `e2e/scan.spec.ts` header + violation tests | ⬜ e2e never executed |
| 18 | Hidden Unicode shown, never HTML | `cloud/web/tests/text.test.ts`, `report.test.tsx`, `invariants.test.ts` | ✅ |
| 19 | Log redaction | `cloud/api/tests/test_logging.py` (7 tests: keys, token shapes, nesting) | ✅ |
| 20 | Actions pinned by SHA, least privilege, trusted publishing | `.github/workflows/*.yml` | ✅ |
| 21 | CodeQL / pip-audit / npm audit / gitleaks green | `ci.yml`, `codeql.yml`, `cloud-ci.yml` | ⬜ never run on a runner |
| 22 | Backups + restore drill | `docs/runbooks/restore-drill.md` — the drill table is empty | ⬜ **blocker** |
| 23 | Privacy, terms, refunds live | `cloud/web/app/legal/*` | ✅ written, ⬜ reviewed |
| 24 | `/.well-known/security.txt` + root `SECURITY.md` | both present | ✅ |
| 25 | Status page linked | footer link to `status.mcpaudit.dev` | ⬜ page not created |
| 26 | ZAP baseline scan of web + API | — | ⬜ |
| 27 | Dogfood: mcp-audit against itself | `ci.yml` dogfood job (offline); a live run has not happened | ⬜ |
| 28 | 72-hour staging soak without alerts | — | ⬜ |

## The honest summary

Every control has code and, where it is testable offline, a test. What has **not** happened:
anything that needs a live model, a container runtime, a browser binary, real payment keys,
or deployed infrastructure. Those are ticks only Srijith can earn, and pretending otherwise
would make this document worse than not having it.

**Before taking money**, the four that matter most:

1. Gate 1 (does the engine actually work on a live model?) — and the cost number that sets
   the prices.
2. The restore drill (line 22).
3. Billing lifecycle against real test-mode keys (line 16).
4. The Playwright suite actually running (line 17).
