# Runbook: bad deploy

## How you know

- `/readyz` failing, 5xx rate above 1%, or the deploy job's smoke step failed.
- Sentry spike starting within a minute of a release.

## Roll back first

```bash
fly releases -a mcp-audit-api                  # find the last good version
fly deploy --image <previous image> -a mcp-audit-api
# or:
fly releases rollback -a mcp-audit-api
```

Then the worker, the same way. Rolling back the API and leaving a new worker running is how
you get a subtle second incident.

## The migration question

Migrations run as the Fly release command and are written expand → migrate → contract, so
the **previous** version of the code must still work against the **new** schema. That makes a
code rollback safe by construction — as long as that rule was actually followed. Check the
migration in the release before rolling back:

- Added a nullable column, added a table, added an index → rollback is safe, leave the
  schema alone.
- Dropped or renamed a column, added a NOT NULL without a default, narrowed a type → the old
  code will fail. **Do not** `alembic downgrade` on production data to fix this; roll the
  schema forward with a corrective migration instead. A downgrade that drops a column drops
  the data in it.

## If the release command itself failed

The deploy stops before the new version serves traffic, so the old one is still up: you are
not in an outage, you are in a failed deploy. Read the release logs, fix the migration,
deploy again.

```bash
fly logs -a mcp-audit-api | grep -i alembic
```

## Web

Vercel keeps every deployment: promote the previous one from the dashboard or
`npx vercel rollback`. The web app is a client — rolling it back cannot corrupt anything,
so do it early rather than debugging in production.

## Afterwards

- What did CI not catch? Add that test. `cloud-ci.yml` already applies every migration to an
  empty database and rolls it back; if the failure was schema-shaped, the gap is a test
  against *data*.
- If the cause was a verdict-affecting change to the engine, note it in the changelog:
  somebody's CI result changed because of us.
