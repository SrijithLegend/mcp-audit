# Runbook: database restore, and the drill

**A backup nobody has restored is a rumour.** ROADMAP Gate 7 requires this drill to have
been done once, with the date and the measured time recorded below.

## What exists

- **Neon PITR** — continuous, with a retention window set on the project. This is the real
  backup.
- **Weekly logical dump** to object storage, from a scheduled job:
  ```bash
  pg_dump --format=custom --no-owner --no-privileges "$DATABASE_URL" > mcpaudit-$(date -u +%F).dump
  ```
  This is the one that survives losing the Neon account, which PITR does not.

## Restoring

1. **Do not restore over production.** Restore to a new branch or database, point a staging
   API at it, and look before you switch anything.
   ```bash
   # Neon: branch from a point in time
   neonctl branches create --name restore-$(date -u +%FT%H%M) --parent-timestamp 2026-09-24T09:00:00Z
   ```
2. Check it is actually the data you wanted, not an empty schema:
   ```sql
   SELECT count(*) FROM scans;
   SELECT max(created_at) FROM scans;
   SELECT count(*) FROM target_secrets;   -- these are encrypted; see below
   ```
3. Point staging at the restored branch, run `alembic current` to confirm the schema version
   matches the code, and click through one scan report.
4. Only then repoint production, and announce the window of lost writes if there is one.

## The encryption catch

`target_secrets` rows are AES-GCM under `HEADER_ENC_KEY`, which lives in Fly secrets and
**not** in the database. A restore is useless for those rows unless that key is still the
one that encrypted them. So:

- Keep a copy of `HEADER_ENC_KEY` in a password manager, not only in Fly.
- If the key is gone, the rows are gone: null them, pause the affected monitors, and ask
  those customers to re-enter their headers. Say so plainly rather than letting monitors
  fail authentication quietly.

## From the logical dump

```bash
createdb mcpaudit_restore
pg_restore --dbname mcpaudit_restore --no-owner --no-privileges mcpaudit-2026-09-24.dump
```

## Drill record

Repeat every six months and after any schema change big enough to be scary.

| Date | Restored to | Wall-clock | Result | Notes |
|---|---|---|---|---|
| — | — | — | not yet run | Gate 7 blocker: this table must have a row before launch |
