# Runbook: Anthropic outage

## How you know

- Scans finishing as `failed` with `error_code: api_error`, or succeeding with verdict
  `INCONCLUSIVE` and a note about API errors.
- Sentry filling with `APIStatusError` / `APITimeoutError` from the worker.
- `status.anthropic.com` says so.

## What is already handled

- **Per-trial failures do not fail a scan.** A trial that errors is recorded with
  `stop_reason: api_error`; if more than 30% of trials on either arm errored, the verdict
  is `INCONCLUSIVE` rather than a confident `CLEAN`. That distinction is the whole reason
  INCONCLUSIVE exists — do not "fix" it into CLEAN.
- **Auth failures abort immediately** instead of burning ten trials on the same rejection.
- **The quota reservation is refunded** when the failure is ours (`ApiError`), so customers
  are not charged a scan for our bad day. A capture failure — their server not answering —
  is not refunded, on purpose.
- The SDK already retries 429 and 5xx four times with backoff.

## Do

1. Confirm it is them, not us: `curl -s https://status.anthropic.com/api/v2/status.json`.
   Then check our own key is not the problem — a revoked key looks identical from a
   distance:
   ```bash
   fly ssh console -a mcp-audit-worker -C "python -c \"
   import anthropic; print(anthropic.Anthropic().models.list().data[0].id)\""
   ```
2. Post on the status page, and say that the CLI still works with the reader's own key.
3. **Stop the queue from grinding.** If every job is failing, pause the worker rather than
   retrying into a wall:
   ```bash
   fly scale count worker=0 -a mcp-audit-worker
   ```
   Queued jobs stay in Redis; scans stay `queued`, which is honest.
4. When Anthropic recovers, scale back up:
   ```bash
   fly scale count worker=1 -a mcp-audit-worker
   ```
   Jobs resume. A `run_scan` that already succeeded is a no-op (the row is terminal), so a
   replayed job cannot spend twice.
5. Re-run anything that landed as `INCONCLUSIVE` during the window. Those verdicts are not
   wrong, but they are not answers either.

## Do not

- Do not raise `max_tries` to push jobs through an outage. Three attempts against a dead
  API is enough; more is just cost.
- Do not lower `API_ERROR_SHARE` in `differ.py` so runs stop coming out INCONCLUSIVE. That
  threshold is the thing keeping a broken run from being reported as clean.

## Over when

Queue depth back to zero, no `api_error` in the last 15 minutes of worker logs, and the
status page updated to resolved.
