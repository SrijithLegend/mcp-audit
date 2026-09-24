/**
 * k6 load test (ROADMAP Phase 7).
 *
 *   k6 run -e BASE=http://localhost:8000 -e TOKEN=mcpa_... cloud/infra/loadtest.js
 *
 * Two things are being measured, and only one of them is throughput:
 *
 * 1. **Quota safety under real concurrency.** 50 submissions against a quota of 10 must
 *    produce exactly 10 acceptances. The unit test proves the lock; this proves it through
 *    the whole stack, with connection pooling and a real event loop in the way.
 *  2. **That the API stays responsive while the worker is saturated.** Reads must not queue
 *     behind scan submissions.
 *
 * Run it against staging, never production: submissions cost model time, so point it at an
 * environment whose ANTHROPIC_API_KEY is empty (the scans will fail as api_error, which is
 * fine — the quota accounting is what is under test) or accept the bill.
 */
import http from "k6/http";
import { check, group, sleep } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

const BASE = __ENV.BASE || "http://localhost:8000";
const TOKEN = __ENV.TOKEN || "";
const QUOTA = Number(__ENV.QUOTA || 10);

const accepted = new Counter("scans_accepted");
const overQuota = new Counter("scans_over_quota");
const rateLimited = new Counter("scans_rate_limited");
const unexpected = new Counter("scans_unexpected_status");
const readLatency = new Trend("read_latency_ms", true);
const readOk = new Rate("read_ok");

export const options = {
  scenarios: {
    // The race: everything arrives at once, on purpose.
    quota_race: {
      executor: "shared-iterations",
      vus: 50,
      iterations: 50,
      exec: "submit",
      maxDuration: "2m",
    },
    // Meanwhile, ordinary reads must stay fast.
    reads: {
      executor: "constant-vus",
      vus: 10,
      duration: "1m",
      exec: "read",
      startTime: "1s",
    },
  },
  thresholds: {
    // A read path that degrades while scans are submitted means the submission path is
    // holding a connection or a lock it should not.
    "read_latency_ms": ["p(95)<500"],
    "read_ok": ["rate>0.99"],
    "scans_unexpected_status": ["count==0"],
  },
};

function headers(extra = {}) {
  return {
    "content-type": "application/json",
    authorization: `Bearer ${TOKEN}`,
    ...extra,
  };
}

/** A distinct inventory per iteration, so the 24-hour result cache does not answer. */
function inventory(marker) {
  return {
    format: "mcp-audit/inventory@1",
    instructions: `load test ${marker}`,
    tools: [
      {
        name: "read_file",
        description: "Read a file from disk.",
        input_schema: { type: "object", properties: { path: { type: "string" } }, required: ["path"] },
      },
    ],
    source: `loadtest:${marker}`,
  };
}

export function submit() {
  const response = http.post(
    `${BASE}/v1/scans`,
    JSON.stringify({ inventory: inventory(`${__VU}-${__ITER}-${Date.now()}`) }),
    { headers: headers({ "idempotency-key": `${__VU}-${__ITER}` }) },
  );

  if (response.status === 202 || response.status === 200) {
    accepted.add(1);
  } else if (response.status === 402) {
    overQuota.add(1);
  } else if (response.status === 429) {
    // Expected: scan creation is limited to 10/min/org. Raise the limit for the run if you
    // want the quota number to be the only thing under test.
    rateLimited.add(1);
  } else if (response.status === 503) {
    // The spend breaker. Also a pass: it is supposed to say no.
    rateLimited.add(1);
  } else {
    unexpected.add(1);
    console.error(`unexpected ${response.status}: ${response.body}`);
  }
}

export function read() {
  group("reads stay fast while scans are submitted", () => {
    const response = http.get(`${BASE}/v1/me`, { headers: headers() });
    readLatency.add(response.timings.duration);
    readOk.add(response.status === 200);
    check(response, { "me is 200": (r) => r.status === 200 });
    sleep(0.2);
  });
}

export function handleSummary(data) {
  const acceptedCount = data.metrics.scans_accepted?.values.count ?? 0;
  const refused =
    (data.metrics.scans_over_quota?.values.count ?? 0) +
    (data.metrics.scans_rate_limited?.values.count ?? 0);

  const lines = [
    "",
    "quota safety",
    "------------",
    `accepted:        ${acceptedCount}`,
    `refused:         ${refused} (402 over quota + 429/503 throttled)`,
    `expected quota:  ${QUOTA}`,
    acceptedCount <= QUOTA
      ? `PASS: no more than the quota was accepted`
      : `FAIL: ${acceptedCount} accepted against a quota of ${QUOTA} -- the reservation is not atomic`,
    "",
  ];
  return { stdout: lines.join("\n") };
}
