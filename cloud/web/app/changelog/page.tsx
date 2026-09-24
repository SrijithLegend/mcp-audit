import type { Metadata } from "next";

import { Card } from "@/components/ui";

export const metadata: Metadata = { title: "Changelog" };

const ENTRIES = [
  {
    date: "unreleased",
    items: [
      "Engine: differential verdicts with Fisher exact + Holm correction, canary stub mode for cross-tool data flow, adaptive escalation, cost ceiling, SARIF/Markdown/JSON reports.",
      "Cloud: hosted scans, rug-pull monitoring, share links, CI tokens, teams, billing.",
      "Not yet published to PyPI, and the fixture gate (Gate 1) has not been run against a live model.",
    ],
  },
];

export default function Changelog() {
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Changelog</h1>
      {ENTRIES.map((entry) => (
        <Card key={entry.date} title={entry.date}>
          <ul className="dim list-disc space-y-1 pl-5 text-sm">
            {entry.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </Card>
      ))}
      <p className="dim text-xs">
        Engine releases are tagged in{" "}
        <a href="https://github.com/SrijithLegend/mcp-audit/releases" rel="noreferrer noopener">
          GitHub releases
        </a>
        . A verdict change never ships without a note here, because it can change your CI result.
      </p>
    </div>
  );
}
