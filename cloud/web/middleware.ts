import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Per-request CSP with a fresh nonce (docs/SECURITY.md §8).
 *
 * A nonce has to be generated per response, so it cannot live in next.config.ts. Next
 * picks the nonce up from the CSP header and puts it on its own inline scripts.
 *
 * Clerk's middleware is deliberately not wired in here: this app talks to our API with a
 * bearer token and every authorisation decision is made server-side by that API. Adding
 * route protection in the edge would duplicate the rule in a second place, and the copy
 * that drifts is the one that lets somebody in.
 */
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const CLERK = "https://*.clerk.accounts.dev https://clerk.mcpaudit.dev";

function policy(nonce: string): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic' ${CLERK}`,
    "style-src 'self' 'unsafe-inline'",
    `connect-src 'self' ${API} ${CLERK} https://*.sentry.io`,
    `img-src 'self' data: blob: ${CLERK} https://img.clerk.com`,
    "font-src 'self' data:",
    "worker-src 'self' blob:",
    "frame-ancestors 'none'",
    "frame-src 'self' https://checkout.dodopayments.com https://test.checkout.dodopayments.com",
    "base-uri 'none'",
    "object-src 'none'",
    "form-action 'self'",
  ].join("; ");
}

export function middleware(request: NextRequest): NextResponse {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);

  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", policy(nonce));
  return response;
}

export const config = {
  // Everything except static assets, which do not execute scripts.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
