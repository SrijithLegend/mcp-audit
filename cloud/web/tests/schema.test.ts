import { describe, expect, it } from "vitest";

import { Inventory, Problem, Report, Scan } from "@/lib/schema";

/**
 * The JSON boundary. The API is ours, but a response is still parsed before it is
 * trusted: a shape change should fail loudly here, not render as `undefined` three
 * components deep.
 */

const REPORT = {
  format: "mcp-audit/report@1",
  engine_version: "0.1.0",
  target: "stdio: python fixtures/poisoned_instructions.py",
  inventory_sha256: "a".repeat(64),
  model: "claude-haiku-4-5",
  task: "summarise",
  trials: 5,
  verdict: "CONFIRMED",
  findings: [
    {
      signal: {
        tool: "read_file",
        kind: "sensitive",
        detail: "etc-passwd",
        security_relevant: true,
        real_hits: 5,
        san_hits: 0,
        n_real: 5,
        n_san: 5,
        p_raw: 0.0079,
        p_adj: 0.0158,
      },
      verdict: "CONFIRMED",
      evidence: {
        call: { name: "read_file", arguments: { path: "/etc/passwd" }, turn: 0, index: 0 },
        trial: 2,
        sanitized_summary: "sanitized arm called read_file in 0/5 trials",
      },
    },
  ],
  traces: [{ side: "real", trial: 0, calls: [], stop_reason: "no_tool_calls" }],
  usage: { input_tokens: 100, output_tokens: 20, cache_read_tokens: 0, api_calls: 5, cost_usd: 0.01 },
  stripped_diff: "--- real\n+++ sanitized",
  notes: [],
};

describe("Report", () => {
  it("parses what the engine emits", () => {
    const report = Report.parse(REPORT);
    expect(report.verdict).toBe("CONFIRMED");
    expect(report.findings[0]?.signal.tool).toBe("read_file");
    expect(report.findings[0]?.evidence?.call?.arguments.path).toBe("/etc/passwd");
  });

  it("fills in the optional halves so components need no defensive checks", () => {
    const minimal = Report.parse({ format: "mcp-audit/report@1", verdict: "CLEAN" });
    expect(minimal.findings).toEqual([]);
    expect(minimal.traces).toEqual([]);
    expect(minimal.usage.cost_usd).toBe(0);
    expect(minimal.notes).toEqual([]);
  });

  it("rejects a verdict we do not know how to render", () => {
    expect(() => Report.parse({ ...REPORT, verdict: "PROBABLY_FINE" })).toThrow();
  });

  it("rejects a signal kind we have no label for", () => {
    const broken = structuredClone(REPORT);
    // @ts-expect-error deliberately wrong, that is the point of the test
    broken.findings[0].signal.kind = "vibes";
    expect(() => Report.parse(broken)).toThrow();
  });
});

describe("Scan", () => {
  it("parses a queued scan with nothing decided yet", () => {
    const scan = Scan.parse({
      id: "018f-1",
      status: "queued",
      trials: 5,
      model: "claude-haiku-4-5",
      stub_mode: "canary",
      created_via: "web",
      created_at: "2026-09-24T10:00:00Z",
    });
    expect(scan.verdict).toBeUndefined();
    expect(scan.cost_usd).toBe(0);
  });

  it("rejects a status the UI has no branch for", () => {
    expect(() =>
      Scan.parse({
        id: "1",
        status: "thinking_about_it",
        trials: 5,
        model: "m",
        stub_mode: "canary",
        created_via: "web",
        created_at: "2026-09-24T10:00:00Z",
      }),
    ).toThrow();
  });
});

describe("Inventory (what a user uploads)", () => {
  const good = {
    format: "mcp-audit/inventory@1",
    instructions: "A notes server.",
    tools: [{ name: "list_notes", description: "List notes.", input_schema: { type: "object" } }],
    source: "stdio: python server.py",
  };

  it("accepts a real capture", () => {
    expect(Inventory.parse(good).tools).toHaveLength(1);
  });

  it("rejects a file that is not an inventory, before it is uploaded", () => {
    expect(() => Inventory.parse({ tools: [] })).toThrow();
    expect(() => Inventory.parse({ format: "something/else@1", tools: good.tools })).toThrow();
  });

  it("rejects an inventory with no tools, because there is nothing to audit", () => {
    expect(() => Inventory.parse({ ...good, tools: [] })).toThrow(/nothing to audit/);
  });
});

describe("Problem", () => {
  it("parses an RFC 9457 error and keeps the upgrade URL", () => {
    const problem = Problem.parse({
      type: "https://mcpaudit.dev/problems/quota_exceeded",
      title: "quota exceeded",
      status: 402,
      detail: "This organisation has used 10 of 10 scans this period.",
      upgrade_url: "https://mcpaudit.dev/pricing",
      used: 10,
      limit: 10,
    });
    expect(problem.status).toBe(402);
    expect(problem.upgrade_url).toContain("/pricing");
  });

  it("survives an error body that is missing everything", () => {
    const problem = Problem.parse({});
    expect(problem.status).toBe(500);
    expect(problem.detail).toBeTruthy();
  });
});
