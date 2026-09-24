"use client";

import Link from "next/link";

import { usePlans } from "@/lib/api";
import { Card, Spinner, Table, Row, Cell, ButtonLink } from "@/components/ui";

/**
 * Rendered from `GET /v1/plans`, so the page cannot drift from the limits the API
 * actually enforces (plans.py is the single source of truth).
 */
export default function Pricing() {
  const plans = usePlans();
  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-xl font-semibold">Pricing</h1>
        <p className="dim max-w-2xl text-sm">
          The CLI is free and MIT licensed and produces the same verdicts. These plans buy hosted
          runs on our API key, history, rug-pull monitoring and teams.
        </p>
      </header>

      {plans.isLoading && <Spinner label="Loading plans" />}
      {plans.isError && (
        <Card>
          <p className="text-sm">
            Could not load live plan limits. The canonical table is in{" "}
            <a href="https://github.com/SrijithLegend/mcp-audit/blob/main/docs/ROADMAP.md" rel="noreferrer noopener">
              docs/ROADMAP.md §5.1
            </a>
            .
          </p>
        </Card>
      )}

      {plans.data && (
        <div className="grid gap-4 md:grid-cols-3">
          {plans.data.map((plan) => (
            <Card key={plan.plan} title={plan.plan.toUpperCase()}>
              <p className="text-lg font-semibold">
                {plan.price_monthly_usd === 0 ? "Free" : `$${plan.price_monthly_usd}/mo`}
              </p>
              {plan.price_yearly_usd > 0 && (
                <p className="dim text-xs">or ${plan.price_yearly_usd}/yr</p>
              )}
              <ul className="dim mt-3 space-y-1 text-xs">
                <li>{plan.scans_per_month} hosted scans / month</li>
                <li>up to {plan.max_trials} trials per arm</li>
                <li>{plan.remote_targets} remote targets</li>
                <li>
                  {plan.monitors === 0
                    ? "no monitoring"
                    : `${plan.monitors} monitors, every ${Math.round(plan.monitor_min_interval_minutes / 60)}h`}
                </li>
                <li>{plan.retention_days} days of history</li>
                <li>{plan.api_tokens} CI tokens</li>
                <li>
                  {plan.seats} seat{plan.seats === 1 ? "" : "s"}
                  {plan.extra_seat_usd ? ` (+$${plan.extra_seat_usd}/seat)` : ""}
                </li>
                <li>{plan.custom_task ? "custom scan tasks" : "default scan task only"}</li>
              </ul>
              <div className="mt-4">
                {plan.price_monthly_usd === 0 ? (
                  <ButtonLink href="/app/scans/new">Start free</ButtonLink>
                ) : (
                  <ButtonLink href="/app/settings/billing" variant="primary">
                    Choose {plan.plan}
                  </ButtonLink>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      <Card title="What every plan includes">
        <Table head={["", "included"]}>
          <Row>
            <Cell>Verdict engine</Cell>
            <Cell>identical to the open-source CLI — same thresholds, same statistics</Cell>
          </Row>
          <Row>
            <Cell>Exports</Cell>
            <Cell>JSON, Markdown, SARIF for GitHub code scanning</Cell>
          </Row>
          <Row>
            <Cell>Share links</Cell>
            <Cell>public, redacted, revocable — for telling a maintainer what you found</Cell>
          </Row>
          <Row>
            <Cell>Safety</Cell>
            <Cell>no tool execution, no stdio in the cloud, no storage of your LLM keys</Cell>
          </Row>
        </Table>
      </Card>

      <p className="dim text-xs">
        Billing runs through Dodo Payments as merchant of record, so local taxes are handled.{" "}
        <Link href="/legal/refunds">Refund policy</Link>.
      </p>
    </div>
  );
}
