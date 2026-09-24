"use client";

import Link from "next/link";

import { useMe, useScans } from "@/lib/api";
import { ago, money, shortHash, visible } from "@/lib/text";
import {
  Alert,
  ButtonLink,
  Card,
  Cell,
  Empty,
  Meter,
  Row,
  Spinner,
  Table,
  VerdictBadge,
} from "@/components/ui";

export default function Dashboard() {
  const me = useMe();
  const scans = useScans();

  if (me.isLoading) return <Spinner label="Loading your organisation" />;
  if (me.isError) {
    return (
      <Alert kind="error">
        Could not reach the API. If you are running this locally, start it with{" "}
        <code>uvicorn mcp_audit_cloud.main:app --reload</code> and set{" "}
        <code>NEXT_PUBLIC_DEV_EMAIL</code>.
      </Alert>
    );
  }

  const rows = scans.data?.items ?? [];
  const counts = rows.reduce<Record<string, number>>((acc, scan) => {
    const key = scan.verdict ?? scan.status;
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Scans</h1>
          <p className="dim text-xs">
            {me.data?.current_org?.name} · {me.data?.plan} plan
          </p>
        </div>
        <ButtonLink href="/app/scans/new" variant="primary">
          New scan
        </ButtonLink>
      </header>

      <div className="grid gap-4 md:grid-cols-3">
        <Card title="This period">
          <Meter
            used={me.data?.usage.scans_used ?? 0}
            limit={me.data?.usage.scans_limit ?? 0}
            label="hosted scans"
          />
          <p className="dim mt-2 text-xs">
            {money(me.data?.usage.cost_usd ?? 0)} of model time so far. The CLI is free and
            unlimited.
          </p>
        </Card>
        <Card title="Recent verdicts">
          {Object.keys(counts).length === 0 ? (
            <Empty>Nothing scanned yet.</Empty>
          ) : (
            <ul className="space-y-1 text-xs">
              {Object.entries(counts).map(([key, count]) => (
                <li key={key} className="flex justify-between">
                  <span>{key}</span>
                  <span className="dim">{count}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Where to go next">
          <ul className="dim space-y-1 text-xs">
            <li>
              <Link href="/app/targets">Targets</Link> — remote endpoints you scan repeatedly
            </li>
            <li>
              <Link href="/app/monitors">Monitors</Link> — catch a server that changes under you
            </li>
            <li>
              <Link href="/app/settings/tokens">CI tokens</Link> — scan from your pipeline
            </li>
          </ul>
        </Card>
      </div>

      <Card title="History">
        {scans.isLoading ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <Empty>
            No scans yet. <Link href="/app/scans/new">Upload an inventory</Link> to start.
          </Empty>
        ) : (
          <Table head={["verdict", "status", "target", "trials", "cost", "when", ""]}>
            {rows.map((scan) => (
              <Row key={scan.id}>
                <Cell>
                  {scan.verdict ? <VerdictBadge verdict={scan.verdict} /> : <span className="dim">—</span>}
                </Cell>
                <Cell>{scan.status}</Cell>
                <Cell className="max-w-xs truncate">
                  {scan.target_id
                    ? visible(scan.target_id.slice(0, 8))
                    : shortHash(scan.inventory_id ?? "")}
                </Cell>
                <Cell>{scan.trials}</Cell>
                <Cell>{money(scan.cost_usd)}</Cell>
                <Cell className="dim">{ago(scan.created_at)}</Cell>
                <Cell>
                  <Link href={`/app/scans/${scan.id}`}>open</Link>
                </Cell>
              </Row>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
