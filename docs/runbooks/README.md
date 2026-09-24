# Runbooks

Written to be read at 3am by someone who did not write the code — which, in a year, is
you. Each one says how to tell it is happening, what to do first, and how to know it is
over.

| Runbook | Symptom |
|---|---|
| [anthropic-outage.md](anthropic-outage.md) | Scans failing with `api_error`; INCONCLUSIVE verdicts |
| [spend-spike.md](spend-spike.md) | Daily spend breaker tripped, or an unexpected Anthropic bill |
| [leaked-secret.md](leaked-secret.md) | A key, token or webhook secret is exposed |
| [webhook-backlog.md](webhook-backlog.md) | Queue depth climbing, scans stuck in `queued` |
| [bad-deploy.md](bad-deploy.md) | 5xx rate up, `/readyz` failing after a release |
| [restore-drill.md](restore-drill.md) | Database restore, and the drill that proves it works |

## Before anything else

1. **Say something.** Update the status page. A five-word note beats silence.
2. **Check the breakers, not the code.** `GET /healthz`, `GET /readyz`, Fly machine
   status, the daily spend counter in Redis. Most incidents are one of those.
3. **Remember the CLI is unaffected.** Hosted scanning being down does not stop anyone
   from running `uvx mcp-audit scan ...` with their own key. Say so in the status note —
   it turns an outage into an inconvenience.
4. **Do not disable a security control to clear an incident.** Not the SSRF guard, not
   the spend breaker, not the quota reservation. If one of them is the cause, that is the
   incident, and the fix goes through a review.

## Numbers worth knowing by heart

- Job timeout: 10 minutes. A scan that takes longer is stuck, not slow.
- Scan cost ceiling: `SCAN_COST_CEILING_USD` (default $1.00) per scan, enforced by the
  engine before any model call.
- Daily spend breaker: `DAILY_SPEND_LIMIT_USD` (default $25). Fails **closed** when Redis
  is unreachable, so "the breaker is broken" means scans are refused, not unlimited.
- Retention sweep: 03:20 UTC daily. It deletes; there is no archive to recover from.
- Grace period on a failed payment: 7 days, features stay on.
