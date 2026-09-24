"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, useCreateScan, useMe, useTargets } from "@/lib/api";
import { Inventory } from "@/lib/schema";
import {
  Alert,
  Button,
  ButtonLink,
  Card,
  Field,
  inputClass,
  Meter,
} from "@/components/ui";

type Tab = "upload" | "remote" | "cli";

/**
 * Three ways to start a scan, and the middle one is the only one that involves us
 * touching a server at all.
 *
 * There is deliberately no "run this command for me" tab: capturing a stdio server means
 * executing it, and that happens on the user's machine, never ours (invariant 3).
 */
export default function NewScan() {
  const [tab, setTab] = useState<Tab>("upload");
  const me = useMe();
  const targets = useTargets();
  const create = useCreateScan();
  const router = useRouter();

  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [targetId, setTargetId] = useState("");
  const [trials, setTrials] = useState(5);
  const [task, setTask] = useState("");
  const [headers, setHeaders] = useState("");

  const entitlements = me.data?.entitlements;
  const overQuota =
    me.data !== undefined && me.data.usage.scans_used >= me.data.usage.scans_limit;

  function readFile(file: File) {
    setParseError(null);
    void file.text().then((text) => {
      try {
        // Validated client-side before it is ever uploaded: a clear message here beats a
        // 422 from the API, and the API validates again anyway.
        setInventory(Inventory.parse(JSON.parse(text)));
      } catch (error) {
        setInventory(null);
        setParseError(
          error instanceof Error
            ? `That file is not an mcp-audit inventory: ${error.message.slice(0, 300)}`
            : "That file could not be read.",
        );
      }
    });
  }

  function submit() {
    const body: Record<string, unknown> = { trials };
    if (task.trim() && entitlements?.custom_task) body.task = task.trim();
    if (tab === "remote") {
      body.target_id = targetId;
      const parsed = parseHeaders(headers);
      if (Object.keys(parsed).length > 0) body.headers = parsed;
    } else {
      body.inventory = inventory;
    }
    create.mutate(body, { onSuccess: (scan) => router.push(`/app/scans/${scan.id}`) });
  }

  const ready = tab === "remote" ? Boolean(targetId) : Boolean(inventory);

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">New scan</h1>
        <p className="dim text-sm">
          The scan runs the same task twice — once with the server&apos;s prose, once without — and
          compares what the model called.
        </p>
      </header>

      {overQuota && (
        <Alert kind="warn" action={<ButtonLink href="/pricing">See plans</ButtonLink>}>
          This organisation has used its {me.data?.usage.scans_limit} hosted scans for the period.
          The CLI still works and gives the same verdict.
        </Alert>
      )}

      <div className="flex gap-2" role="tablist" aria-label="Scan source">
        {(
          [
            ["upload", "Upload an inventory"],
            ["remote", "Remote HTTP target"],
            ["cli", "From the CLI"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`rounded border px-3 py-1.5 text-xs ${
              tab === key ? "border-[var(--color-accent)]" : "border-[var(--border)]"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "upload" && (
        <Card title="Inventory JSON">
          <p className="dim mb-3 text-xs">
            Capture it with <code>mcp-audit inspect &lt;command&gt; --out inventory.json</code>. Stdio
            capture runs the server, so it happens on your machine — we only ever see the result.
          </p>
          <input
            type="file"
            accept="application/json,.json"
            className={inputClass}
            aria-label="Inventory JSON file"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) readFile(file);
            }}
          />
          {parseError && (
            <div className="mt-3">
              <Alert kind="error">{parseError}</Alert>
            </div>
          )}
          {inventory && (
            <p className="mt-3 text-xs">
              {inventory.tools.length} tools
              {inventory.server_name ? ` from ${inventory.server_name}` : ""},{" "}
              {inventory.instructions ? "with" : "without"} server instructions.
            </p>
          )}
        </Card>
      )}

      {tab === "remote" && (
        <Card title="Remote target">
          {targets.data?.items.length === 0 ? (
            <p className="dim text-xs">
              No targets yet. <a href="/app/targets">Add one</a> — https only, and we check it
              resolves to a public address before we will connect.
            </p>
          ) : (
            <div className="space-y-3">
              <Field label="Target" htmlFor="target">
                <select
                  id="target"
                  className={inputClass}
                  value={targetId}
                  onChange={(event) => setTargetId(event.target.value)}
                >
                  <option value="">Choose a target…</option>
                  {targets.data?.items.map((target) => (
                    <option key={target.id} value={target.id}>
                      {target.name} — {target.url}
                    </option>
                  ))}
                </select>
              </Field>
              <Field
                label="Headers for this scan (optional)"
                hint="One per line, 'Name: value'. Kept encrypted in Redis for an hour and never stored or returned."
                htmlFor="headers"
              >
                <textarea
                  id="headers"
                  rows={3}
                  className={inputClass}
                  placeholder="Authorization: Bearer ..."
                  value={headers}
                  onChange={(event) => setHeaders(event.target.value)}
                />
              </Field>
            </div>
          )}
        </Card>
      )}

      {tab === "cli" && (
        <Card title="Scan from the CLI">
          <pre className="hostile surface rounded p-3 text-xs">
            {`mcp-audit login --token mcpa_...   # create one in Settings → Tokens
mcp-audit scan npx -y @some/mcp-server --cloud`}
          </pre>
          <p className="dim mt-2 text-xs">
            The CLI captures locally, uploads the inventory, and polls for the report. Drop{" "}
            <code>--cloud</code> and it runs on your own key instead, free.
          </p>
        </Card>
      )}

      {tab !== "cli" && (
        <Card title="Options">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label={`Trials per arm (max ${entitlements?.max_trials ?? 5} on your plan)`}
              hint="One run is noise. Five is the smallest sample where 5/5 against 0/5 means anything."
              htmlFor="trials"
            >
              <input
                id="trials"
                type="number"
                min={2}
                max={entitlements?.max_trials ?? 5}
                className={inputClass}
                value={trials}
                onChange={(event) => setTrials(Number(event.target.value))}
              />
            </Field>
            <Field
              label="Task"
              hint={
                entitlements?.custom_task
                  ? "What to ask the model to do. Leave empty for the default, server-agnostic task."
                  : "Custom tasks are a Pro feature; free scans use the default task."
              }
              htmlFor="task"
            >
              <input
                id="task"
                className={inputClass}
                disabled={!entitlements?.custom_task}
                placeholder="Summarise what is in this server"
                value={task}
                onChange={(event) => setTask(event.target.value)}
              />
            </Field>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button variant="primary" disabled={!ready || create.isPending} onClick={submit}>
              {create.isPending ? "Queueing…" : `Run ${trials * 2} trials`}
            </Button>
            <span className="dim text-xs">
              Uses 1 of your {me.data?.usage.scans_limit} scans this period.
            </span>
          </div>
          {me.data && (
            <div className="mt-3 max-w-xs">
              <Meter
                used={me.data.usage.scans_used}
                limit={me.data.usage.scans_limit}
                label="scans used"
              />
            </div>
          )}
          {create.isError && (
            <div className="mt-3">
              <Alert
                kind="error"
                action={
                  create.error instanceof ApiError && create.error.upgradeUrl ? (
                    <ButtonLink href="/pricing">Upgrade</ButtonLink>
                  ) : undefined
                }
              >
                {create.error.message}
              </Alert>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

function parseHeaders(raw: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of raw.split("\n")) {
    const index = line.indexOf(":");
    if (index > 0) out[line.slice(0, index).trim()] = line.slice(index + 1).trim();
  }
  return out;
}
