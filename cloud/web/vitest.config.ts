import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": resolve(__dirname, ".") } },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["tests/**/*.test.{ts,tsx}"],
    // Playwright owns e2e; vitest owns the pure functions and the components that render
    // hostile text, which is where the security-relevant logic in this app lives.
    exclude: ["e2e/**", "node_modules/**"],
  },
});
