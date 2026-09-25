# Runbook: unexpected cost

**There is no inference bill to spike.** Scans run on the customer's own Anthropic key
(invariant 3'), the Cloud holds no LLM credential, and a grep test fails the build if any
code path here could call a model. So this runbook is shorter than it used to be, and the
first question is different.

## If you get an Anthropic invoice you did not expect

That is not hosted scanning. Check, in order:

1. **Your own development and testing.** The live fixture gate (`pytest -m gate`) and any
   `bench/run.py` run without `--dry-run` spend real money on *your* key. That is almost
   always the answer.
2. **A key leak.** If the spend is not yours, treat it as a compromised credential and go to
   [leaked-secret.md](leaked-secret.md) immediately.
3. **An invariant regression.** Run the grep tests. If `test_the_cloud_never_calls_a_model`
   fails, somebody reintroduced an inference path into the hosted service and that is the
   incident:
   ```bash
   uv run pytest -q tests/test_invariants.py::test_the_cloud_never_calls_a_model
   uv run --directory cloud/api pytest -q tests/test_economics.py
   ```

## If infrastructure cost climbs

The costs that scale with customers now are storage, bandwidth and queue time.

```sql
-- biggest consumers of storage this period
SELECT o.plan, count(*) AS reports, pg_size_pretty(sum(pg_column_size(s.report))::bigint) AS report_bytes
FROM scans s JOIN orgs o ON o.id = s.org_id
WHERE s.created_at > date_trunc('month', now())
GROUP BY o.plan ORDER BY sum(pg_column_size(s.report)) DESC;
```

- **Reports are capped per plan** and truncated on the way in (arguments to 512 chars, at
  most 64 traces). An org over its plan's `reports_per_month` cannot store more.
- **Retention deletes**, nightly, per plan. If storage grows anyway, check that
  `expire_data` is actually running: `redis-cli LLEN arq:queue` and the worker logs.
- **Monitors** are one HTTP round trip and a hash each. A Pro org with 25 hourly monitors is
  600 requests a day, which is noise. If monitor traffic is not noise, look for a monitor
  pointed at something enormous and check the 2 MB response cap is being applied.

## What to do about a customer costing more than they pay

Storage is the only lever, and the plan limits already bound it. If someone is genuinely
expensive, they are hitting `reports_per_month` and being refused — which is the system
working. Do not add an inference path to "help" them: point them at the CLI, which is free
and unlimited and is the thing they actually want.

## Do not

- Do not add an `ANTHROPIC_API_KEY` to the Cloud config to "just run this one scan for a
  customer". That reverses D12, reintroduces a bill with no ceiling, and the grep test will
  fail the build — correctly.
- Do not accept a customer's API key to run scans on their behalf. A breach then reaches
  their billing account, and we have no business holding that.
