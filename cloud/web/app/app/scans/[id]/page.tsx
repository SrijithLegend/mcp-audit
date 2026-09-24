"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import {
  ArmView,
  EvidenceList,
  FindingsTable,
  Limits,
  StrippedDiff,
  VerdictBanner,
} from "@/components/report";
import { Alert, Button, ButtonLink, Card, Spinner } from "@/components/ui";
import { reportUrl, useCancelScan, useReport, useScan, useShare } from "@/lib/api";
import { ago, visible } from "@/lib/text";

export default function ScanPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const scan = useScan(id);
  const done = scan.data?.status === "succeeded";
  const report = useReport(id, done);
  const cancel = useCancelScan(id);
  const share = useShare(id);
  const [shareUrl, setShareUrl] = useState<string | null>(null);

  if (scan.isLoading) return <Spinner label="Loading scan" />;
  if (scan.isError) return <Alert kind="error">{scan.error.message}</Alert>;
  const row = scan.data;
  if (!row) return null;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Scan</h1>
          <p className="dim text-xs">
            {row.status} · queued {ago(row.created_at)} · {row.trials} trials per arm ·{" "}
            {visible(row.model)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {["queued", "running"].includes(row.status) && (
            <Button variant="danger" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
              Cancel
            </Button>
          )}
          {done && (
            <>
              <ButtonLink href={reportUrl(id, "json")} external>
                JSON
              </ButtonLink>
              <ButtonLink href={reportUrl(id, "md")} external>
                Markdown
              </ButtonLink>
              <ButtonLink href={reportUrl(id, "sarif")} external>
                SARIF
              </ButtonLink>
              {row.share_token ? (
                <Button onClick={() => share.revoke.mutate(undefined, { onSuccess: () => setShareUrl(null) })}>
                  Revoke share link
                </Button>
              ) : (
                <Button
                  onClick={() =>
                    share.create.mutate(undefined, { onSuccess: (data) => setShareUrl(data.url) })
                  }
                >
                  Create share link
                </Button>
              )}
            </>
          )}
        </div>
      </header>

      {shareUrl && (
        <Alert kind="info">
          Public, redacted and revocable: <code>{shareUrl}</code>. The task text, the target and the
          stripped-prose diff are removed before it is served.
        </Alert>
      )}

      {["queued", "running"].includes(row.status) && (
        <Card>
          <p className="text-sm" role="status">
            {row.status === "queued" ? "Waiting for a worker" : "Running trials"}… this page updates
            itself every couple of seconds.
          </p>
          <p className="dim mt-1 text-xs">
            {row.trials * 2} agent conversations, up to 6 turns each. Usually under a minute.
          </p>
        </Card>
      )}

      {row.status === "failed" && (
        <Alert kind="error">
          <p>
            <strong>{row.error_code}</strong>: {visible(row.error_detail ?? "no detail")}
          </p>
          <p className="dim mt-1 text-xs">
            If this was our fault — an API outage — the scan did not count against your quota.
          </p>
        </Alert>
      )}

      {row.status === "canceled" && <Alert kind="info">This scan was cancelled.</Alert>}

      {done && report.isLoading && <Spinner label="Loading report" />}
      {done && report.data && (
        <>
          <VerdictBanner report={report.data} />
          <FindingsTable report={report.data} />
          <EvidenceList report={report.data} />
          <ArmView report={report.data} />
          <StrippedDiff diff={report.data.stripped_diff} />
          <Limits />
        </>
      )}
    </div>
  );
}
