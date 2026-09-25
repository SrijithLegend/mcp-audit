# cloud/ — the hosted service

AGPL-3.0 (see `cloud/LICENSE`). The engine under `src/mcp_audit/` stays MIT.

Cloud sells history, rug-pull monitoring, CI integration, sharing and teams. It does **not**
sell verdicts: those come from the CLI, free and unlimited, and what lands here is the
report that CLI produced. The CLI is never crippled to push people here (CLAUDE.md).

## Hard rules

- **No inference, ever.** This service holds no LLM key and cannot call a model. Scans run
  where the key already is — the user's machine or their CI — and we ingest the finished
  report. Two grep tests enforce it (`tests/test_invariants.py` and
  `tests/test_economics.py`), and `mcp_audit.meta` exists so this package can read engine
  constants without importing the agent loop. This is what makes hosted scanning cost us
  nothing to operate, so it is an invariant, not a preference (D12, invariant 3').
- **No stdio, ever.** Cloud accepts a finished report, or an `https://` Streamable HTTP URL
  fetched through the SSRF guard for `tools/list` only. No code path here spawns a process
  from user input (invariant 3, docs/SECURITY.md §2).
- **No tool execution.** Same grep, same invariant.
- **No customer LLM keys.** Not stored, not accepted, not wanted.

## Local development

```bash
docker compose -f cloud/infra/docker-compose.yml up -d     # postgres 16 + redis
cp cloud/api/.env.example cloud/api/.env                   # fill in the blanks
uv run --directory cloud/api alembic upgrade head
uv run --directory cloud/api uvicorn mcp_audit_cloud.main:app --reload
uv run --directory cloud/api arq mcp_audit_cloud.worker.WorkerSettings
uv run --directory cloud/api pytest -q                     # needs the containers
pnpm --dir cloud/web dev
```

`DEV_AUTH_BYPASS=1` accepts `Authorization: Bearer dev:<email>` so you can work without
Clerk. It refuses to start in any environment other than `local`.

## Layout

```
api/mcp_audit_cloud/
  main.py          app factory, middleware, error handlers
  config.py        pydantic-settings; fails fast on a missing secret
  db.py            async engine, session dependency, RLS org scoping
  auth.py          Clerk JWT via JWKS + our own mcpa_ API tokens
  ssrf.py          remote-target guard (docs/SECURITY.md §3)
  ratelimit.py     Redis sliding window
  models/          SQLAlchemy 2 models
  schemas/         pydantic request/response
  routers/         /v1 endpoints + webhooks
  services/        scans, quota, monitors, notify, headers
  billing/         BillingProvider protocol, Dodo, Polar
  worker.py        arq: monitors (capture + hash) and retention. Never a model
  services/ingest.py  storing a report the user's own run produced
  plans.py         the single source of truth for plan limits
```
