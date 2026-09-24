import type { NextConfig } from "next";

/**
 * Security headers (docs/SECURITY.md §8).
 *
 * The CSP has no `unsafe-inline` for scripts: Next's inline bootstrap gets a nonce from
 * `middleware.ts` instead. Styles still need `unsafe-inline` because Tailwind's runtime
 * injects them; that is a much smaller hole than script-src would be, and there is no
 * way around it today without a build-time extract.
 */
const api = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const clerk = "https://*.clerk.accounts.dev https://clerk.mcpaudit.dev";

const csp = [
  "default-src 'self'",
  `script-src 'self' 'strict-dynamic' 'nonce-NONCE' ${clerk}`,
  "style-src 'self' 'unsafe-inline'",
  `connect-src 'self' ${api} ${clerk} https://*.sentry.io`,
  `img-src 'self' data: blob: ${clerk} https://img.clerk.com`,
  "font-src 'self' data:",
  "worker-src 'self' blob:",
  "frame-ancestors 'none'",
  "frame-src 'self' https://checkout.dodopayments.com https://test.checkout.dodopayments.com",
  "base-uri 'none'",
  "object-src 'none'",
  "form-action 'self'",
  "upgrade-insecure-requests",
].join("; ");

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // The CSP itself is set per-request in middleware.ts so it can carry a nonce; these
  // are the headers that do not vary.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
          },
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
      {
        // A shared report must never end up in a search index.
        source: "/share/:path*",
        headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }],
      },
    ];
  },
};

export const CSP_TEMPLATE = csp;
export default config;
