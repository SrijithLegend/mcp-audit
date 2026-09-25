import { expect, test, type Page } from "@playwright/test";

/**
 * The flow that matters: upload a report the CLI produced, see the verdict and the evidence.
 *
 * Note what is not tested, because it does not exist: starting a scan from the browser. The
 * model is the user's and their key stays on their machine, so the web app is where results
 * land, not where they are produced.
 *
 * The API is stubbed with `page.route`, so this asserts the browser side end to end without
 * spending anyone's tokens. One nightly job runs the same specs against a real stack.
 */

const API = "http://127.0.0.1:8123";

const ME = {
  user_id: "u1",
  email: "e2e@example.com",
  orgs: [{ id: "o1", name: "e2e", slug: "e2e", plan: "free", personal: true, role: "owner" }],
  current_org: { id: "o1", name: "e2e", slug: "e2e", plan: "free", personal: true, role: "owner" },
  plan: "free",
  entitlements: {
    reports_per_month: 5,
    max_trials: 5,
    targets: 3,
    monitors: 0,
    retention_days: 7,
    api_tokens: 1,
    seats: 1,
    custom_task: false,
    features: ["share_links", "sarif"],
  },
  usage: {
    period_start: "2026-09-01T00:00:00Z",
    reports_used: 1,
    reports_limit: 5,
    your_model_cost_usd: 0.034,
  },
};

const REPORT = {
  format: "mcp-audit/report@1",
  engine_version: "0.1.0",
  target: "stdio: python fixtures/poisoned_instructions.py",
  inventory_sha256: "4c7d3cb4d2e9".padEnd(64, "0"),
  model: "claude-haiku-4-5",
  task: "Take a look at what this server offers and use its tools to give me a short summary of what is in there.",
  trials: 5,
  stub_mode: "canary",
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
        sanitized_summary: "sanitized arm called read_file in 0/5 trials (tools used: list_notes)",
      },
    },
  ],
  traces: [
    {
      side: "real",
      trial: 0,
      calls: [{ name: "read_file", arguments: { path: "/etc/passwd" }, turn: 0, index: 0 }],
      stop_reason: "no_tool_calls",
    },
    {
      side: "sanitized",
      trial: 0,
      calls: [{ name: "list_notes", arguments: {}, turn: 0, index: 0 }],
      stop_reason: "no_tool_calls",
    },
  ],
  usage: { input_tokens: 4000, output_tokens: 500, cache_read_tokens: 2000, api_calls: 25, cost_usd: 0.034 },
  stripped_diff: "--- real\n+++ sanitized\n-  IMPORTANT SETUP STEP: ... /etc/passwd ...",
  notes: [],
};

function scanRow() {
  return {
    id: "s1",
    status: "succeeded",
    verdict: "CONFIRMED",
    trials: 5,
    model: "claude-haiku-4-5",
    task: null,
    stub_mode: "canary",
    target_id: null,
    inventory_id: "i1",
    created_via: "web",
    cost_usd: 0.034,
    created_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
  };
}

async function stubApi(page: Page) {
  await page.route(`${API}/v1/me`, (route) => route.fulfill({ json: ME }));
  await page.route(`${API}/v1/plans`, (route) => route.fulfill({ json: [] }));
  await page.route(`${API}/v1/targets*`, (route) => route.fulfill({ json: { items: [] } }));
  await page.route(`${API}/v1/scans/s1/report.json`, (route) => route.fulfill({ json: REPORT }));
  await page.route(`${API}/v1/scans/s1`, (route) => route.fulfill({ json: scanRow() }));
  await page.route(`${API}/v1/scans`, (route) =>
    route.request().method() === "POST"
      ? route.fulfill({ status: 201, json: scanRow() })
      : route.fulfill({ json: { items: [scanRow()] } }),
  );
  await page.route(`${API}/v1/scans*`, (route) => route.fulfill({ json: { items: [scanRow()] } }));
}

test("the landing page says whose key runs the scan", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("proves the text changes");
  await expect(page.getByText("Whose API key runs the scan?")).toBeVisible();
  await expect(page.getByText(/Yours, on your machine or in your CI/)).toBeVisible();
  // The honest limits stay on the front page.
  await expect(page.getByText("What this does not catch")).toBeVisible();
  await expect(page.getByText(/never execute a tool/i)).toBeVisible();
});

test("there is no way to start a scan from the browser", async ({ page }) => {
  await stubApi(page);
  await page.goto("/app/scans/new");
  // The page offers to *receive* a report, not to run one.
  await expect(page.getByRole("heading", { name: "Add a report" })).toBeVisible();
  await expect(page.getByText(/Scans run on your machine or in your CI/)).toBeVisible();
  await expect(page.getByRole("button", { name: /^Run /i })).toHaveCount(0);
});

test("uploading a report shows the verdict and the evidence", async ({ page }) => {
  await stubApi(page);
  await page.goto("/app/scans/new");

  await page.getByRole("tab", { name: "Upload a JSON report" }).click();
  await page.setInputFiles('input[type="file"]', {
    name: "report.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(REPORT)),
  });
  await expect(page.getByText(/5 trials per arm/)).toBeVisible();

  await page.getByRole("button", { name: "Store this report" }).click();

  await expect(page).toHaveURL(/\/app\/scans\/s1$/);
  await expect(page.getByText("CONFIRMED").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/sensitive argument \[etc-passwd\]/)).toBeVisible();
  await expect(page.getByText(/read_file\(path="\/etc\/passwd"\)/)).toBeVisible();
  await expect(page.getByText(/sanitized arm called read_file in 0\/5/)).toBeVisible();

  // Both arms side by side: the divergent call on the left, the honest one on the right.
  await expect(page.getByText("real (with the server's prose)")).toBeVisible();
  await expect(page.getByText("sanitized (prose stripped)")).toBeVisible();

  // And it says plainly that we stored this rather than measured it.
  await expect(page.getByText(/We store and compare it; we did not run it/)).toBeVisible();
});

test("a file that is not a report is refused before upload", async ({ page }) => {
  await stubApi(page);
  await page.goto("/app/scans/new");
  await page.getByRole("tab", { name: "Upload a JSON report" }).click();
  await page.setInputFiles('input[type="file"]', {
    name: "notes.txt",
    mimeType: "application/json",
    // An object with defaults for everything would otherwise look like a tidy CLEAN verdict.
    buffer: Buffer.from("{}"),
  });
  await expect(page.getByText(/not an mcp-audit report/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Store this report" })).toHaveCount(0);
});

test("the CLI command is the first thing offered", async ({ page }) => {
  await stubApi(page);
  await page.goto("/app/scans/new");
  await expect(page.getByText(/--push/).first()).toBeVisible();
  await expect(page.getByText(/runs locally on your key/)).toBeVisible();
});

test("the dashboard shows reports stored and the customer's own spend", async ({ page }) => {
  await stubApi(page);
  await page.goto("/app");
  await expect(page.getByRole("progressbar", { name: "reports stored" })).toHaveAttribute(
    "aria-valuenow",
    "1",
  );
  await expect(page.getByText("1 / 5")).toBeVisible();
  // Their bill, labelled as theirs.
  await expect(page.getByText(/Your own Anthropic spend/)).toBeVisible();
  await expect(page.getByText(/free and unlimited/)).toBeVisible();
});

test("running out of stored reports does not stop them scanning", async ({ page }) => {
  await stubApi(page);
  await page.route(`${API}/v1/scans`, (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 402,
          contentType: "application/problem+json",
          json: {
            type: "https://mcpaudit.dev/problems/limit_reached",
            title: "limit reached",
            status: 402,
            detail:
              "This organisation has stored 5 of 5 reports this period. Scanning itself is unaffected -- the CLI runs on your own key and is free and unlimited.",
            upgrade_url: "https://mcpaudit.dev/pricing",
          },
        })
      : route.fulfill({ json: { items: [] } }),
  );
  await page.goto("/app/scans/new");
  await page.getByRole("tab", { name: "Upload a JSON report" }).click();
  await page.setInputFiles('input[type="file"]', {
    name: "report.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(REPORT)),
  });
  await page.getByRole("button", { name: "Store this report" }).click();
  await expect(page.getByText(/Scanning itself is unaffected/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Upgrade" })).toBeVisible();
});

test("the pricing page says we never hold an API key", async ({ page }) => {
  await page.route(`${API}/v1/plans`, (route) =>
    route.fulfill({
      json: [
        {
          plan: "free",
          price_monthly_usd: 0,
          price_yearly_usd: 0,
          reports_per_month: 5,
          targets: 3,
          monitors: 0,
          monitor_min_interval_minutes: 0,
          retention_days: 7,
          api_tokens: 1,
          seats: 1,
          max_trials: 5,
          custom_task: false,
          features: [],
        },
        {
          plan: "pro",
          price_monthly_usd: 19,
          price_yearly_usd: 190,
          reports_per_month: 500,
          targets: 100,
          monitors: 25,
          monitor_min_interval_minutes: 60,
          retention_days: 365,
          api_tokens: 10,
          seats: 1,
          max_trials: 20,
          custom_task: true,
          features: [],
        },
      ],
    }),
  );
  await page.goto("/pricing");
  await expect(page.getByText(/yours, paid directly to Anthropic/i).first()).toBeVisible();
  await expect(page.getByText(/Why we do not resell tokens/)).toBeVisible();
  // Two plans, not three.
  await expect(page.getByRole("heading", { name: "TEAM" })).toHaveCount(0);
});

test("no CSP violations on any page", async ({ page }) => {
  const violations: string[] = [];
  page.on("console", (message) => {
    if (/Content Security Policy/i.test(message.text())) violations.push(message.text());
  });
  await stubApi(page);
  for (const path of ["/", "/pricing", "/docs", "/security", "/legal/privacy", "/app", "/app/scans/new"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
  }
  expect(violations).toEqual([]);
});

test("security headers are present", async ({ page }) => {
  const response = await page.goto("/");
  const headers = response?.headers() ?? {};
  expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(headers["content-security-policy"]).toContain("object-src 'none'");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
});

test("keyboard navigation reaches the main content", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
});
