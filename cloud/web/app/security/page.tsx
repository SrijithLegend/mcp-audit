import type { Metadata } from "next";

import { Card } from "@/components/ui";

export const metadata: Metadata = { title: "Security" };

export default function Security() {
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Security</h1>
      <Card title="Report a vulnerability">
        <p className="text-sm">
          Privately, through{" "}
          <a
            href="https://github.com/SrijithLegend/mcp-audit/security/advisories/new"
            rel="noreferrer noopener"
          >
            GitHub Security Advisories
          </a>{" "}
          or by email to <code>srijithshaibu@gmail.com</code>. Acknowledgement within 72 hours, an
          assessment within 7 days, a fix before disclosure, and credit unless you decline.
        </p>
      </Card>

      <Card title="How this service is built">
        <ul className="dim list-disc space-y-1.5 pl-5 text-sm">
          <li>
            <strong>No code execution.</strong> Hosted scans accept an inventory JSON or an{" "}
            <code>https://</code> URL. Nothing here spawns a process from user input, and a test
            greps the codebase to prove it.
          </li>
          <li>
            <strong>No tool execution.</strong> Every model tool call is answered by a dry-run
            stub. Same test.
          </li>
          <li>
            <strong>Remote fetches are guarded.</strong> https and port 443 only, DNS resolved
            once, private and metadata addresses refused, the connection pinned to the validated
            IP so rebinding cannot move it, no redirects, response capped.
          </li>
          <li>
            <strong>Your auth headers.</strong> Encrypted with AES-GCM, kept in a separate table
            from the target, never returned by the API after you set them, never logged, never in
            a report. One-off scan headers live in Redis for an hour.
          </li>
          <li>
            <strong>Isolation between organisations.</strong> Every query is org-scoped in the
            repository layer, with Postgres row-level security behind it as a second wall.
            Cross-organisation requests get 404, not 403 — existence is information too.
          </li>
          <li>
            <strong>CI tokens.</strong> 32 random bytes, shown once, stored as sha256, revocable
            with immediate effect.
          </li>
          <li>
            <strong>We never hold your LLM key.</strong> Hosted scans run on ours and are metered;
            the CLI uses yours and we never see it.
          </li>
          <li>
            <strong>Your inventories are confidential.</strong> They name your internal tools. They
            are never used in a benchmark or a marketing page without explicit opt-in.
          </li>
        </ul>
        <p className="dim mt-3 text-xs">
          The full threat model, including what we consider out of scope:{" "}
          <a
            href="https://github.com/SrijithLegend/mcp-audit/blob/main/docs/SECURITY.md"
            rel="noreferrer noopener"
          >
            docs/SECURITY.md
          </a>
          .
        </p>
      </Card>

      <Card title="Attacker-controlled text in this UI">
        <p className="dim text-sm">
          Tool descriptions and model arguments are hostile input. This app renders them as text in
          a monospace block, never as markdown or HTML, and it makes invisible characters visible
          as <code>&lt;U+200B&gt;</code> rather than hiding them — a payload written in zero-width
          joiners is something you should be able to see.
        </p>
      </Card>
    </div>
  );
}
