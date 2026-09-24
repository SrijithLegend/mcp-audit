# Runbook: queue backlog / scans stuck in `queued`

## How you know

- Alert: queue depth > 50 for 10 minutes.
- Customers reporting a scan that never starts; rows with `status = 'queued'` and a
  `queued_at` older than a few minutes.

```sql
SELECT status, count(*), min(queued_at) AS oldest
FROM scans WHERE status IN ('queued','running') GROUP BY status;
```

```bash
redis-cli LLEN arq:queue            # jobs waiting
fly status -a mcp-audit-worker      # are there any workers at all
fly logs -a mcp-audit-worker | tail -50
```

## The four causes, in order of likelihood

1. **No workers running.** A crash loop, or somebody scaled to zero during an incident and
   did not scale back. `fly scale count worker=1 -a mcp-audit-worker`.
2. **Every job failing and retrying.** Usually an Anthropic outage — see
   [anthropic-outage.md](anthropic-outage.md) — or a bad deploy, see
   [bad-deploy.md](bad-deploy.md).
3. **The enqueue silently failed.** `queue.enqueue()` logs `queue.enqueue_failed` and
   returns None rather than losing the scan row: the row exists as `queued` with nothing to
   run it. Re-enqueue by id:
   ```bash
   fly ssh console -a mcp-audit-worker -C "python -c \"
   import asyncio
   from mcp_audit_cloud.queue import enqueue
   asyncio.run(enqueue('run_scan', '<scan-id>'))\""
   ```
4. **Genuine load.** Workers scale 1–3; more than that and the Anthropic rate limit becomes
   the bottleneck rather than our CPU, so scaling further just moves the queue.

## Outbound customer webhooks

Delivery is best-effort with three attempts and backoff; a receiver that is down loses that
notification and the log line says so (`webhook.rejected` / `webhook.error`). There is no
delivery queue to drain, by design — the report is always in the API, and a missed
notification is not a lost scan. If a customer needs guaranteed delivery, they poll
`GET /v1/scans`.

A destination that is refused outright (`webhook.refused`) is the SSRF guard doing its job:
the customer pointed us at a private address. Tell them; do not exempt it.

## Over when

Queue depth zero, no row `queued` for more than two minutes, and the oldest `running` scan
younger than the 10-minute job timeout.
