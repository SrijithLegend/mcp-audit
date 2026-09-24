"use client";

import { useState } from "react";

import type { Finding, Report, Trace } from "@/lib/schema";
import { callLine, money, pct, rate, shortHash, visible } from "@/lib/text";

import { Card, Cell, Empty, Hostile, Row, Table, VerdictBadge, VERDICT_HEADLINE } from "./ui";

const SIGNAL_NAMES: Record<string, string> = {
  called: "tool called",
  called_first: "called first",
  sensitive: "sensitive argument",
  canary_flow: "cross-tool data flow",
  optional_populated: "optional parameter filled",
};

function signalName(finding: Finding): string {
  const { kind, detail } = finding.signal;
  const base = SIGNAL_NAMES[kind] ?? kind;
  return detail ? `${base} [${visible(detail)}]` : base;
}

export function VerdictBanner({ report }: { report: Report }) {
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3">
        <VerdictBadge verdict={report.verdict} big />
        <p className="text-sm">{VERDICT_HEADLINE[report.verdict]}</p>
      </div>
      <dl className="dim mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-4">
        <div>
          <dt className="inline">model </dt>
          <dd className="inline text-[var(--fg)]">{visible(report.model)}</dd>
        </div>
        <div>
          <dt className="inline">trials/arm </dt>
          <dd className="inline text-[var(--fg)]">
            {report.trials}
            {report.escalated ? " (escalated)" : ""}
          </dd>
        </div>
        <div>
          <dt className="inline">inventory </dt>
          <dd className="inline text-[var(--fg)]">{shortHash(report.inventory_sha256)}</dd>
        </div>
        <div>
          <dt className="inline">cost </dt>
          <dd className="inline text-[var(--fg)]">{money(report.usage.cost_usd)}</dd>
        </div>
      </dl>
      {report.notes.length > 0 && (
        <ul className="dim mt-3 space-y-1 text-xs">
          {report.notes.map((note) => (
            <li key={note}>note: {visible(note)}</li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function FindingsTable({ report }: { report: Report }) {
  const reported = report.findings.filter((finding) => finding.verdict !== "CLEAN");
  if (reported.length === 0) {
    return (
      <Card title="Findings">
        <Empty>No signal cleared the thresholds on either arm.</Empty>
      </Card>
    );
  }
  return (
    <Card title="Findings">
      <Table head={["verdict", "tool", "signal", "real", "sanitized", "p (adj)", "direction"]}>
        {reported.map((finding) => {
          const s = finding.signal;
          const away = s.real_hits / (s.n_real || 1) < s.san_hits / (s.n_san || 1);
          return (
            <Row key={`${s.tool}:${s.kind}:${s.detail}`}>
              <Cell>
                <VerdictBadge verdict={finding.verdict} />
              </Cell>
              <Cell className="font-semibold">{visible(s.tool)}</Cell>
              <Cell>{signalName(finding)}</Cell>
              <Cell>
                {rate(s.real_hits, s.n_real)} <span className="dim">({pct(s.real_hits, s.n_real)})</span>
              </Cell>
              <Cell>
                {rate(s.san_hits, s.n_san)} <span className="dim">({pct(s.san_hits, s.n_san)})</span>
              </Cell>
              <Cell>{s.security_relevant ? s.p_adj.toFixed(4) : `${s.p_raw.toFixed(4)} raw`}</Cell>
              <Cell>{away ? "steered away" : "steered toward"}</Cell>
            </Row>
          );
        })}
      </Table>
    </Card>
  );
}

export function EvidenceList({ report }: { report: Report }) {
  const withEvidence = report.findings.filter((f) => f.verdict !== "CLEAN" && f.evidence?.call);
  if (withEvidence.length === 0) return null;
  return (
    <Card title="Evidence">
      <ul className="space-y-4">
        {withEvidence.map((finding) => (
          <li key={`${finding.signal.tool}:${finding.signal.kind}:${finding.signal.detail}`}>
            <p className="text-xs font-semibold">
              {visible(finding.signal.tool)} — {signalName(finding)}
            </p>
            <Hostile label={`real arm, trial ${finding.evidence?.trial ?? "?"}`}>
              {callLine({
                name: finding.evidence?.call?.name ?? "",
                arguments: finding.evidence?.call?.arguments ?? {},
              })}
            </Hostile>
            <p className="dim mt-1 text-xs">{visible(finding.evidence?.sanitized_summary ?? "")}</p>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/**
 * The side-by-side arm view: the whole argument, visible.
 *
 * A call that appears on the left and not on the right is the finding. Showing both arms
 * trial by trial is what lets somebody check our verdict instead of believing it.
 */
export function ArmView({ report }: { report: Report }) {
  const [trial, setTrial] = useState(0);
  const real = report.traces.filter((t) => t.side === "real");
  const sanitized = report.traces.filter((t) => t.side === "sanitized");
  const trials = Math.max(real.length, sanitized.length);
  if (trials === 0) return null;

  const left = real.find((t) => t.trial === trial) ?? real[trial];
  const right = sanitized.find((t) => t.trial === trial) ?? sanitized[trial];
  const onlyOnLeft = new Set(
    (left?.calls ?? [])
      .map((c) => c.name)
      .filter((name) => !(right?.calls ?? []).some((c) => c.name === name)),
  );

  return (
    <Card
      title="Both arms, trial by trial"
      action={
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Trial">
          {Array.from({ length: trials }, (_, index) => (
            <button
              key={index}
              role="tab"
              aria-selected={index === trial}
              onClick={() => setTrial(index)}
              className={`rounded border px-2 py-0.5 text-xs ${
                index === trial ? "border-[var(--color-accent)]" : "border-[var(--border)]"
              }`}
            >
              {index}
            </button>
          ))}
        </div>
      }
    >
      <div className="grid gap-4 md:grid-cols-2">
        <Arm title="real (with the server's prose)" trace={left} highlight={onlyOnLeft} />
        <Arm title="sanitized (prose stripped)" trace={right} highlight={new Set()} />
      </div>
    </Card>
  );
}

function Arm({
  title,
  trace,
  highlight,
}: {
  title: string;
  trace: Trace | undefined;
  highlight: Set<string>;
}) {
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold">{title}</h3>
      {!trace ? (
        <Empty>No trace for this trial.</Empty>
      ) : trace.calls.length === 0 ? (
        <p className="dim text-xs">
          No tools called{trace.stop_reason === "api_error" ? " (API error)" : ""}.
        </p>
      ) : (
        <ol className="space-y-2">
          {trace.calls.map((call, index) => (
            <li
              key={`${call.name}-${index}`}
              className={`surface rounded p-2 text-xs ${
                highlight.has(call.name) ? "border-l-2 border-l-[var(--color-confirmed)]" : ""
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">{visible(call.name)}</span>
                <span className="dim">turn {call.turn}</span>
              </div>
              <pre className="hostile mt-1">{visible(JSON.stringify(call.arguments, null, 1))}</pre>
            </li>
          ))}
        </ol>
      )}
      {trace && <p className="dim text-xs">stop reason: {trace.stop_reason}</p>}
    </div>
  );
}

export function StrippedDiff({ diff }: { diff: string }) {
  if (!diff) return null;
  return (
    <Card title="What sanitization removed">
      <p className="dim mb-2 text-xs">
        The verdict rests on this text being absent from the sanitized arm, so here it is.
        Shown as text, never rendered.
      </p>
      <Hostile>{diff.slice(0, 40000)}</Hostile>
    </Card>
  );
}

export function Limits() {
  return (
    <Card title="What this does not catch">
      <ul className="dim list-disc space-y-1 pl-5 text-xs">
        <li>
          Steering through tool or parameter <strong>names</strong>, and through{" "}
          <code>enum</code>/<code>const</code> values: they are the call surface and have to
          survive sanitization.
        </li>
        <li>Injection through tool <em>results</em>. Tools are never executed.</li>
        <li>
          A server that changes after this scan. The report carries the inventory hash;
          monitoring narrows the window but does not close it.
        </li>
        <li>Steering specific to another model. This run used one, and it is named above.</li>
      </ul>
    </Card>
  );
}
