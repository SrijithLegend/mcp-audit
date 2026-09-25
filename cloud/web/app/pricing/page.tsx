"use client";

import Link from "next/link";

import { usePlans } from "@/lib/api";
import { ButtonLink, Card, Cell, Row, Spinner, Table } from "@/components/ui";

/**
 * Rendered from `GET /v1/plans`, so the page cannot drift from the limits the API actually
 * enforces (plans.py is the single source of truth).
 */
export default function Pricing() {
  const plans = usePlans();
  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-xl font-semibold">Pricing</h1>
        <p className="dim max-w-2xl text-sm">
          You pay for the auditing product. You do not pay us for tokens, and we do not pay for
          yours: scans run on your machine or in your CI, on your own Anthropic key, and that key
          never reaches us. What these plans buy is everything a local CLI cannot do — history,
          diffs over time, rug-pull monitoring, sharing, and CI integration.
        </p>
        <p className="dim max-w-2xl text-xs">
          The scanner itself is MIT licensed and free forever, with no limits of any kind:{" "}
          <code>uvx mcp-audit scan &lt;server&gt;</code>. If all you want is a verdict, you never
          need an account.
        </p>
      </header>

      {plans.isLoading && <Spinner label="Loading plans" />}
      {plans.isError && (
        <Card>
          <p className="text-sm">
            Could not load live plan limits. The canonical table is in{" "}
            <a
              href="https://github.com/SrijithLegend/mcp-audit/blob/main/docs/ROADMAP.md"
              rel="noreferrer noopener"
            >
              docs/ROADMAP.md §5.1
            </a>
            .
          </p>
        </Card>
      )}

      {plans.data && (
        <div className="grid gap-4 md:grid-cols-2">
          {plans.data.map((plan) => (
            <Card key={plan.plan} title={plan.plan.toUpperCase()}>
              <p className="text-lg font-semibold">
                {plan.price_monthly_usd === 0 ? "Free" : `$${plan.price_monthly_usd}/mo`}
              </p>
              {plan.price_yearly_usd > 0 && (
                <p className="dim text-xs">or ${plan.price_yearly_usd}/yr</p>
              )}
              <p className="dim mt-2 text-xs">
                Model cost: <strong>yours, paid directly to Anthropic</strong>
              </p>
              <ul className="dim mt-3 space-y-1 text-xs">
                <li>{plan.reports_per_month} reports kept / month</li>
                <li>{plan.targets} servers tracked</li>
                <li>up to {plan.max_trials} trials per arm</li>
                <li>
                  {plan.monitors === 0
                    ? "no rug-pull monitoring"
                    : `${plan.monitors} monitors, every ${Math.max(
                        1,
                        Math.round(plan.monitor_min_interval_minutes / 60),
                      )}h`}
                </li>
                <li>{plan.retention_days} days of history</li>
                <li>{plan.api_tokens} CI tokens</li>
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
            <Cell>the open-source CLI — same thresholds, same statistics, no hosted-only logic</Cell>
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
            <Cell>
              no tool execution, no stdio in the cloud, and we hold no API key of yours — ours or
              Anthropic&apos;s
            </Cell>
          </Row>
        </Table>
      </Card>

      <Card title="Why we do not resell tokens">
        <p className="dim text-sm">
          We could bundle model usage and mark it up. We do not, for two reasons. Holding your
          Anthropic key would make a breach of our database a breach of your billing account, and a
          security product should not create that risk to save you a config line. And bundling
          means metering: you would be rationed by our budget rather than your own, and a deep
          twenty-trial audit of a large server would be something we discourage instead of
          something you just run.
        </p>
        <p className="dim mt-2 text-sm">
          The practical effect: scan as much as you like, as deeply as you like. Anthropic bills you
          for what you use — typically a few cents per scan on <code>claude-haiku-4-5</code> — and we
          charge a flat fee for keeping the results useful.
        </p>
      </Card>

      <p className="dim text-xs">
        Billing runs through Dodo Payments as merchant of record, so local taxes are handled.{" "}
        <Link href="/legal/refunds">Refund policy</Link>. Need seats for a team?{" "}
        <a href="mailto:srijithshaibu@gmail.com">Ask</a> — it is built and we will turn it on.
      </p>
    </div>
  );
}
