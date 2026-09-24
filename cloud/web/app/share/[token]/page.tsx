import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ArmView, EvidenceList, FindingsTable, Limits, VerdictBanner } from "@/components/report";
import { Alert, Card } from "@/components/ui";
import { API } from "@/lib/api";
import { SharedReport } from "@/lib/schema";

/**
 * A public, read-only, redacted report.
 *
 * Server-rendered so the page works without JavaScript for whoever was sent the link, and
 * `noindex` because a share link exists to tell one maintainer something, not to publish a
 * list of which servers a company runs.
 */
export const metadata: Metadata = {
  title: "Shared report",
  robots: { index: false, follow: false },
};

export default async function SharedPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const response = await fetch(`${API}/v1/shared/${encodeURIComponent(token)}`, {
    cache: "no-store",
  });
  if (!response.ok) notFound();
  const parsed = SharedReport.safeParse(await response.json());
  if (!parsed.success) notFound();
  const { report } = parsed.data;

  return (
    <div className="space-y-6">
      <Card>
        <h1 className="text-lg font-semibold">Shared mcp-audit report</h1>
        <p className="dim mt-1 text-xs">
          Read-only and redacted: the task text, the target and the removed-prose diff are not
          included. Whoever shared this can revoke the link at any time.
        </p>
      </Card>
      <VerdictBanner report={report} />
      <FindingsTable report={report} />
      <EvidenceList report={report} />
      <ArmView report={report} />
      <Limits />
      <Alert kind="info">
        You can reproduce this yourself for free:{" "}
        <code>uvx mcp-audit scan &lt;the server&gt;</code>. Same engine, same thresholds.
      </Alert>
    </div>
  );
}
