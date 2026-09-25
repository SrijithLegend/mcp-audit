"use client";

import Link from "next/link";
import { useState } from "react";

import { useMonitorChanges, useMonitors } from "@/lib/api";
import { ago, shortHash, visible } from "@/lib/text";
import { Alert, Card, Cell, Empty, Hostile, Row, Spinner, Table } from "@/components/ui";

/**
 * Rug-pull history. The interesting row is a prose change with an unchanged call surface:
 * the tools did not move, the instructions did.
 */
export default function Monitors() {
  const monitors = useMonitors();
  const [open, setOpen] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Monitors</h1>
        <p className="dim text-sm">
          A server that was clean when you installed it can ship new descriptions tomorrow. We
          re-capture on a schedule and compare the hash — that part needs no model, so we can do it
          while you sleep. When it changes you get the diff and the command to re-audit it on your
          own key.
        </p>
      </header>

      {monitors.isLoading && <Spinner />}
      {monitors.isError && <Alert kind="error">{monitors.error.message}</Alert>}

      {monitors.data && monitors.data.items.length === 0 && (
        <Card>
          <Empty>
            No monitors. Add one from <Link href="/app/targets">Targets</Link> — monitoring needs a
            remote HTTP target, because an uploaded inventory is only re-checked when your CI uploads
            it again.
          </Empty>
        </Card>
      )}

      {monitors.data?.items.map((monitor) => (
        <Card
          key={monitor.id}
          title={`Monitor ${monitor.id.slice(0, 8)}`}
          action={
            <button className="text-xs underline" onClick={() => setOpen(open === monitor.id ? null : monitor.id)}>
              {open === monitor.id ? "hide history" : "show history"}
            </button>
          }
        >
          <dl className="dim grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-4">
            <div>
              <dt className="inline">state </dt>
              <dd className="inline text-[var(--fg)]">
                {monitor.enabled ? "watching" : `paused — ${visible(monitor.paused_reason ?? "")}`}
              </dd>
            </div>
            <div>
              <dt className="inline">last check </dt>
              <dd className="inline text-[var(--fg)]">{ago(monitor.last_checked_at)}</dd>
            </div>
            <div>
              <dt className="inline">last result </dt>
              <dd className="inline text-[var(--fg)]">{visible(monitor.last_status ?? "—")}</dd>
            </div>
            <div>
              <dt className="inline">hash </dt>
              <dd className="inline text-[var(--fg)]">{shortHash(monitor.last_sha256 ?? "")}</dd>
            </div>
          </dl>
          {open === monitor.id && <Changes monitorId={monitor.id} />}
        </Card>
      ))}
    </div>
  );
}

function Changes({ monitorId }: { monitorId: string }) {
  const changes = useMonitorChanges(monitorId);
  if (changes.isLoading) return <Spinner />;
  if (changes.isError) return <Alert kind="error">{changes.error.message}</Alert>;
  const rows = changes.data?.items ?? [];
  if (rows.length === 0) return <Empty>No captures yet.</Empty>;

  return (
    <div className="mt-4 space-y-4">
      {rows.map((change) => (
        <div key={change.id} className="border-t border-[var(--border)] pt-3">
          <p className="text-xs">
            <strong>{ago(change.created_at)}</strong> — {shortHash(change.old_sha256 ?? "first")} →{" "}
            {shortHash(change.new_sha256)}
            {change.scan_id && (
              <>
                {" · "}
                <Link href={`/app/scans/${change.scan_id}`}>see the re-audit</Link>
              </>
            )}
          </p>

          {!change.diff.first_capture && !change.scan_id && (
            <div className="mt-2">
              <Alert kind="warn">
                <p>This server changed and has not been re-audited.</p>
                <pre className="hostile mt-1 text-xs">mcp-audit scan --url &lt;this server&gt; --push</pre>
              </Alert>
            </div>
          )}
          {change.diff.first_capture ? (
            <p className="dim mt-1 text-xs">
              First capture: {change.diff.tools_added.length} tools recorded as the baseline.
            </p>
          ) : (
            <div className="mt-2 space-y-2">
              <Table head={["what", "detail"]}>
                {change.diff.tools_added.length > 0 && (
                  <Row>
                    <Cell>tools added</Cell>
                    <Cell>{change.diff.tools_added.map(visible).join(", ")}</Cell>
                  </Row>
                )}
                {change.diff.tools_removed.length > 0 && (
                  <Row>
                    <Cell>tools removed</Cell>
                    <Cell>{change.diff.tools_removed.map(visible).join(", ")}</Cell>
                  </Row>
                )}
                {change.diff.schema_changed.map((item) => (
                  <Row key={`schema-${item.tool}`}>
                    <Cell>parameters changed</Cell>
                    <Cell>
                      {visible(item.tool)}: {item.params_before.join(", ") || "none"} →{" "}
                      {item.params_after.join(", ") || "none"}
                    </Cell>
                  </Row>
                ))}
                {(change.diff.version_before ?? "") !== (change.diff.version_after ?? "") && (
                  <Row>
                    <Cell>version</Cell>
                    <Cell>
                      {visible(change.diff.version_before ?? "—")} →{" "}
                      {visible(change.diff.version_after ?? "—")}
                    </Cell>
                  </Row>
                )}
              </Table>

              {change.diff.instructions_changed && (
                <div className="grid gap-2 md:grid-cols-2">
                  <Hostile label="instructions before">{change.diff.instructions_before}</Hostile>
                  <Hostile label="instructions after">{change.diff.instructions_after}</Hostile>
                </div>
              )}

              {change.diff.prose_changed.map((item) => (
                <div key={`prose-${item.tool}`} className="grid gap-2 md:grid-cols-2">
                  <Hostile label={`${visible(item.tool)} description before`}>{item.before}</Hostile>
                  <Hostile label={`${visible(item.tool)} description after`}>{item.after}</Hostile>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
