"use client";

import Link from "next/link";

import { useCheckout, useMe, usePlans, usePortal, useSubscription } from "@/lib/api";
import { Alert, Button, Card, Cell, Meter, Row, Spinner, Table } from "@/components/ui";

export default function Billing() {
  const me = useMe();
  const plans = usePlans();
  const subscription = useSubscription();
  const checkout = useCheckout();
  const portal = usePortal();

  const isOwner = me.data?.current_org?.role === "owner";

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Billing</h1>
        <p className="dim text-sm">
          Payments run through Dodo Payments as merchant of record. Plan changes take effect when
          their webhook confirms them, not when a redirect says so.
        </p>
      </header>

      {!isOwner && (
        <Alert kind="info">Only an organisation owner can change billing.</Alert>
      )}

      <Card title="Current plan">
        {subscription.isLoading || me.isLoading ? (
          <Spinner />
        ) : (
          <>
            <Table head={["", ""]}>
              <Row>
                <Cell>plan</Cell>
                <Cell className="font-semibold">{subscription.data?.plan ?? me.data?.plan}</Cell>
              </Row>
              <Row>
                <Cell>status</Cell>
                <Cell>{subscription.data?.status ?? "none"}</Cell>
              </Row>
              {subscription.data?.current_period_end && (
                <Row>
                  <Cell>renews</Cell>
                  <Cell>{new Date(subscription.data.current_period_end).toLocaleDateString()}</Cell>
                </Row>
              )}
              {subscription.data?.cancel_at_period_end && (
                <Row>
                  <Cell>cancellation</Cell>
                  <Cell>at the end of this period; your data stays</Cell>
                </Row>
              )}
            </Table>
            {me.data && (
              <div className="mt-4 max-w-xs">
                <Meter
                  used={me.data.usage.reports_used}
                  limit={me.data.usage.reports_limit}
                  label="reports stored this period"
                />
              </div>
            )}
            {subscription.data?.status === "past_due" && (
              <div className="mt-3">
                <Alert kind="warn">
                  A payment failed. Features stay on for a 7-day grace period — locking a security
                  tool out mid-incident over an expired card would be daft. Update the card in the
                  portal.
                </Alert>
              </div>
            )}
            {subscription.data?.status && subscription.data.status !== "none" && (
              <div className="mt-4">
                <Button
                  disabled={!isOwner || portal.isPending}
                  onClick={() =>
                    portal.mutate(undefined, {
                      onSuccess: (data) => {
                        window.location.href = data.url;
                      },
                    })
                  }
                >
                  Manage payment method
                </Button>
              </div>
            )}
          </>
        )}
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        {plans.data?.map((plan) => (
          <Card key={plan.plan} title={plan.plan.toUpperCase()}>
            <p className="text-lg font-semibold">
              {plan.price_monthly_usd === 0 ? "Free" : `$${plan.price_monthly_usd}/mo`}
            </p>
            <ul className="dim mt-2 space-y-1 text-xs">
              <li>{plan.reports_per_month} reports / month</li>
              <li>{plan.max_trials} trials per arm</li>
              <li>{plan.monitors === 0 ? "no monitoring" : `${plan.monitors} monitors`}</li>
              <li>{plan.retention_days} days of history</li>
            </ul>
            {plan.price_monthly_usd > 0 && (
              <div className="mt-3 flex gap-2">
                {(["month", "year"] as const).map((interval) => (
                  <Button
                    key={interval}
                    size="sm"
                    variant={interval === "month" ? "primary" : "secondary"}
                    disabled={!isOwner || checkout.isPending}
                    onClick={() =>
                      checkout.mutate(
                        { plan: plan.plan, interval },
                        {
                          onSuccess: (data) => {
                            window.location.href = data.url;
                          },
                        },
                      )
                    }
                  >
                    {interval === "month" ? "Monthly" : `Yearly ($${plan.price_yearly_usd})`}
                  </Button>
                ))}
              </div>
            )}
          </Card>
        ))}
      </div>

      {checkout.isError && <Alert kind="error">{checkout.error.message}</Alert>}

      <p className="dim text-xs">
        Downgrading never deletes data: over-limit monitors are paused, history stops being served
        past the new retention window, and nothing is erased that the retention job would not have
        erased anyway. Scanning is never affected by your plan — the CLI runs on your key.{" "}
        <Link href="/legal/refunds">Refund policy</Link>.
      </p>
    </div>
  );
}
