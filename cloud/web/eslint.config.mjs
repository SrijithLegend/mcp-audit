import next from "eslint-config-next";

/**
 * Next's recommended flat config, plus the one rule this codebase cares most about.
 *
 * `no-explicit-any` is left to `tsc --strict` and to tests/invariants.test.ts, which greps
 * for it: adding the typescript-eslint plugin here would be a second type checker to keep
 * in step with the first.
 */
const config = [
  ...next,
  {
    // Hostile text is never HTML here. A test greps for it too, but failing in the editor
    // is faster than failing in CI.
    rules: { "react/no-danger": "error" },
  },
  { ignores: [".next/**", "node_modules/**", "playwright-report/**", "test-results/**"] },
];

export default config;
