"use client";

import { useParams, useRouter } from "next/navigation";
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
import { reportUrl, useDeleteScan, useReport, useScan, useShare } from "@/lib/api";
import { ago, money, visible } from "@/lib/text";

export default function ScanPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const router = useRouter();
  const scan = useScan(id);
  const stored = scan.data?.status === "succeeded";
  const report = useReport(id, stored);
  const share = useShare(id);
  const remove = useDeleteScan();
  const [shareUrl, setShareUrl] = useState<string | null>(null);

  if (scan.isLoading) return <Spinner label="Loading report" />;
  if (scan.isError) return <Alert kind="error">{scan.error.message}</Alert>;
  const row = scan.data;
  if (!row) return null;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Report</h1>
          <p className="dim text-xs">
            scanned {ago(row.finished_at ?? row.created_at)} · {row.trials} trials per arm ·{" "}
            {visible(row.model)} · their cost {money(row.cost_usd)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
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
            <Button
              onClick={() => share.revoke.mutate(undefined, { onSuccess: () => setShareUrl(null) })}
            >
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
          <Button
            variant="danger"
            onClick={() => remove.mutate(id, { onSuccess: () => router.push("/app") })}
          >
            Delete
          </Button>
        </div>
      </header>

      {shareUrl && (
        <Alert kind="info">
          Public, redacted and revocable: <code>{shareUrl}</code>. The task text, the target and the
          stripped-prose diff are removed before it is served.
        </Alert>
      )}

      {report.isLoading && <Spinner label="Loading report" />}
      {report.isError && <Alert kind="error">{report.error.message}</Alert>}
      {report.data && (
        <>
          <Card>
            <p className="dim text-xs">
              {/* An uploaded report is a claim about a run we did not perform. Saying so is
                  the honest framing, and the inventory hash is what makes it checkable. */}
              This report was produced by <strong>mcp-audit {report.data.engine_version}</strong> on
              the uploader&apos;s own machine. We store and compare it; we did not run it. Anyone
              can re-run the same audit against inventory{" "}
              <code>{report.data.inventory_sha256.slice(0, 12)}</code> and get the same verdict up to
              model stochasticity.
            </p>
          </Card>
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
