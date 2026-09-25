# Runbook: spend spike / breaker tripped

Money is the failure mode that can end this product, so the controls are layered and the
outermost one is not in our code.

## The layers, outermost first

1. **Anthropic console spend limit.** Set per environment. If this trips, everything stops
   and nothing we deploy can override it. That is the point.
2. **Daily spend breaker** (`DAILY_SPEND_LIMIT_USD`, default $25). A Redis counter of
   today's estimated spend; new scans get 503 above it. **Fails closed** if Redis is
   unreachable. This is the number that bounds total monthly exposure — about $750 at the
   default — whatever the customer mix does.
3. **Per-org model-time budget** (`plans.included_model_usd`: $0.30 free, $5 Pro, $22 Team),
   enforced in the same locked transaction as the scan-count reservation. This is the layer
   that makes the *unit economics* safe rather than only the total.
4. **Per-scan ceiling**, the lesser of the plan's limit, what is left of that org's budget,
   and `SCAN_COST_CEILING_USD`. Enforced by the engine's cost guard before the first model
   call, so an org with $0.04 left cannot start a $0.50 scan.
5. **Per-org scan count**, derived from the budget, reserved under the same row lock.

## How you know

- 503 responses with `type: .../spend_breaker` and customers saying scanning is paused.
- The Redis counter: `redis-cli GET breaker:spend:$(date -u +%F)` — micro-dollars.
- Anthropic usage dashboard climbing faster than scan count would explain.

## Do

1. **Read the number before touching anything.**
   ```bash
   redis-cli GET "breaker:spend:$(date -u +%F)"        # micro-dollars today
   ```
   Then get the real spend per scan from our own rows, which is the number that matters:
   ```sql
   SELECT date_trunc('hour', finished_at) AS hour,
          count(*)                        AS scans,
          sum(cost_micros)/1e6            AS usd,
          round(avg(cost_micros)/1e6, 4)  AS usd_per_scan
   FROM scans
   WHERE finished_at > now() - interval '24 hours'
   GROUP BY 1 ORDER BY 1 DESC;
   ```
2. **Work out which of the three it is.**
   - *Many scans, normal cost each* → a customer is using what they paid for, or abusing a
     free tier. Check `created_via` and `org_id`; look at `audit_log`.
   - *Few scans, huge cost each* → an inventory with hundreds of tools, or `max_turns`
     being reached every trial. Check `input_tokens` per scan and `stop_reason` in the
     stored traces.
   - *Cost with no scans* → something is calling the API outside the scan path. This is the
     serious one; treat it as a possible key compromise and go to
     [leaked-secret.md](leaked-secret.md).

   Then check whether any org is over its budget, which should be impossible:

   ```sql
   SELECT u.org_id, o.plan, u.scans_used, u.cost_micros/1e6 AS spent_usd
   FROM usage u JOIN orgs o ON o.id = u.org_id
   WHERE u.period_start = date_trunc('month', now())
   ORDER BY u.cost_micros DESC LIMIT 20;
   ```

   Spend above that plan's `included_model_usd` means a reservation was bypassed. That is a
   bug, not a capacity problem: find the code path that created a scan without calling
   `quota.reserve()`.
3. **Contain.** Lower the breaker rather than the per-scan ceiling — it stops new spend
   without changing what a scan means:
   ```bash
   fly secrets set DAILY_SPEND_LIMIT_USD=5 -a mcp-audit-worker -a mcp-audit-api
   ```
   For a single abusive org, revoke its tokens and set its plan to free; the quota
   reservation does the rest.
4. **Tell people.** A breaker trip is a visible outage of hosted scanning. Status page,
   and point at the CLI.

## Do not

- Do not raise the breaker to make the alert stop. Find out why first; that is what the
  breaker bought you.
- Do not remove the per-scan ceiling to let "just this one big server" through. A 400-tool
  inventory at 10 trials is exactly the shape that produces a surprise invoice.

## Afterwards

If the honest cost per scan has moved, the plan table has to move with it: ROADMAP §5.1
says the limits are computed from the measured cost, and `plans.margin_ok()` is the check.
Record the new number in `bench/fixtures.md` and re-run that arithmetic before selling
another month.
