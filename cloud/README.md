# cloud/ — the hosted service

AGPL-3.0 (see `cloud/LICENSE`). The engine under `src/mcp_audit/` stays MIT.

Cloud sells convenience, history, rug-pull monitoring, CI integration and teams. It
runs **the same engine** as the CLI — `mcp_audit.audit()`, unchanged — so a hosted
verdict is a verdict you can reproduce locally for free. The CLI is never crippled to
push people here (CLAUDE.md).

## Hard rules

- **No stdio, ever.** Cloud accepts an inventory JSON captured by the user's own CLI, or
  an `https://` Streamable HTTP URL fetched through the SSRF guard. There is no code
  path here that spawns a process from user input, and `tests/test_invariants.py` greps
  this directory to prove it (invariant 3, docs/SECURITY.md §2).
- **No tool execution.** Same grep, same invariant.
- **No customer LLM keys.** We meter our own (D12).

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
  worker.py        arq settings and jobs
  plans.py         the single source of truth for plan limits
```
