import { defineConfig, devices } from "@playwright/test";

/**
 * e2e against a built app with the API stubbed at the network layer (Gate 4).
 *
 * The API is stubbed rather than mocked in-process because the thing being tested is the
 * whole pipeline a browser goes through: CSP, hydration, polling, rendering a report. A
 * nightly run points the same specs at a real stack.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:3100",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: "npx next start -p 3100",
        port: 3100,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        env: {
          NEXT_PUBLIC_API_URL: "http://127.0.0.1:8123",
          NEXT_PUBLIC_DEV_EMAIL: "e2e@example.com",
        },
      },
});
