"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, useMe, useTargets, useUploadReport } from "@/lib/api";
import { UploadableReport } from "@/lib/schema";
import { Alert, Button, ButtonLink, Card, Field, Meter, inputClass } from "@/components/ui";

type Tab = "cli" | "upload";

/**
 * Adding a report. Note what is *not* here: a "run a scan" button.
 *
 * Scanning needs a model, the model is the user's, and their key belongs on their machine —
 * we neither hold one nor want to. So the flow is: they run the audit locally or in CI, and
 * this page is where the result lands. The CLI tab is deliberately first, because pushing
 * from CI is how anybody serious will use this.
 */
export default function AddReport() {
  const [tab, setTab] = useState<Tab>("cli");
  const me = useMe();
  const targets = useTargets();
  const upload = useUploadReport();
  const router = useRouter();

  const [report, setReport] = useState<UploadableReport | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [targetId, setTargetId] = useState("");

  const overLimit =
    me.data !== undefined && me.data.usage.reports_used >= me.data.usage.reports_limit;

  function readFile(file: File) {
    setParseError(null);
    void file.text().then((text) => {
      try {
        // Validated here before it is uploaded: a clear message beats a 422, and the API
        // validates again anyway because a browser check protects nobody.
        setReport(UploadableReport.parse(JSON.parse(text)));
      } catch (error) {
        setReport(null);
        setParseError(
          error instanceof Error
            ? `That file is not an mcp-audit report: ${error.message.slice(0, 300)}`
            : "That file could not be read.",
        );
      }
    });
  }

  function submit() {
    const body: Record<string, unknown> = { report };
    if (targetId) body.target_id = targetId;
    upload.mutate(body, { onSuccess: (scan) => router.push(`/app/scans/${scan.id}`) });
  }

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Add a report</h1>
        <p className="dim text-sm">
          Scans run on your machine or in your CI, on your own Anthropic key. This is where the
          result is kept, compared over time, and shared.
        </p>
      </header>

      {overLimit && (
        <Alert kind="warn" action={<ButtonLink href="/pricing">See plans</ButtonLink>}>
          This organisation has stored its {me.data?.usage.reports_limit} reports for the period.
          Scanning is unaffected — the CLI is free and unlimited; only keeping the history here is
          capped.
        </Alert>
      )}

      <div className="flex gap-2" role="tablist" aria-label="How to add a report">
        {(
          [
            ["cli", "Push from the CLI or CI"],
            ["upload", "Upload a JSON report"],
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

      {tab === "cli" && (
        <Card title="One command">
          <pre className="hostile surface rounded p-3 text-xs">
            {`# once, to link this organisation
mcp-audit login --token mcpa_...     # create one in Settings -> Tokens

# then, every time -- runs locally on your key, uploads the result
mcp-audit scan npx -y @some/mcp-server --push`}
          </pre>
          <p className="dim mt-3 text-xs">
            In CI, add <code>cloud-token</code> to the action and it pushes automatically. The scan
            still runs in your job on your key; the token only says where to file the report.
          </p>
          <pre className="hostile surface mt-2 rounded p-3 text-xs">
            {`- uses: SrijithLegend/mcp-audit/action@v0
  with:
    command: npx -y @some/mcp-server
    api-key: \${{ secrets.ANTHROPIC_API_KEY }}
    cloud-token: \${{ secrets.MCP_AUDIT_TOKEN }}`}
          </pre>
        </Card>
      )}

      {tab === "upload" && (
        <Card title="Report JSON">
          <p className="dim mb-3 text-xs">
            Produce one with <code>mcp-audit scan &lt;server&gt; --json &gt; report.json</code>.
          </p>
          <input
            type="file"
            accept="application/json,.json"
            className={inputClass}
            aria-label="Report JSON file"
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
          {report && (
            <div className="mt-3 space-y-3">
              <p className="text-xs">
                <strong>{report.verdict}</strong> · {report.trials} trials per arm ·{" "}
                {report.model} · inventory {report.inventory_sha256.slice(0, 12)}
              </p>
              {(targets.data?.items.length ?? 0) > 0 && (
                <Field
                  label="Attach to a target (optional)"
                  hint="Links this report to a server you monitor, so the history lines up."
                  htmlFor="target"
                >
                  <select
                    id="target"
                    className={inputClass}
                    value={targetId}
                    onChange={(event) => setTargetId(event.target.value)}
                  >
                    <option value="">Not attached</option>
                    {targets.data?.items.map((target) => (
                      <option key={target.id} value={target.id}>
                        {target.name}
                      </option>
                    ))}
                  </select>
                </Field>
              )}
              <div className="flex flex-wrap items-center gap-3">
                <Button variant="primary" disabled={upload.isPending} onClick={submit}>
                  {upload.isPending ? "Storing…" : "Store this report"}
                </Button>
                <span className="dim text-xs">
                  Uses 1 of your {me.data?.usage.reports_limit} reports this period.
                </span>
              </div>
            </div>
          )}
          {me.data && (
            <div className="mt-4 max-w-xs">
              <Meter
                used={me.data.usage.reports_used}
                limit={me.data.usage.reports_limit}
                label="reports stored"
              />
            </div>
          )}
          {upload.isError && (
            <div className="mt-3">
              <Alert
                kind="error"
                action={
                  upload.error instanceof ApiError && upload.error.upgradeUrl ? (
                    <ButtonLink href="/pricing">Upgrade</ButtonLink>
                  ) : undefined
                }
              >
                {upload.error.message}
              </Alert>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
