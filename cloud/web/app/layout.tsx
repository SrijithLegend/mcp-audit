import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: { default: "mcp-audit", template: "%s · mcp-audit" },
  description:
    "Differential exploit confirmation for MCP servers: proof that a server's prose changes what a model does, not a guess that it might.",
  robots: { index: true, follow: true },
  openGraph: {
    title: "mcp-audit",
    description: "Confirm whether an MCP server's prose actually steers a model.",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen">
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <Providers>
          <div className="mx-auto max-w-6xl px-4 py-4 sm:px-6">
            <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
              <Link href="/" className="font-semibold">
                mcp-audit
              </Link>
              <nav aria-label="Main" className="flex flex-wrap items-center gap-4 text-xs">
                <Link href="/app">Dashboard</Link>
                <Link href="/pricing">Pricing</Link>
                <Link href="/docs">Docs</Link>
                <Link href="/security">Security</Link>
              </nav>
            </header>
            <main id="main">{children}</main>
            <footer className="dim mt-12 flex flex-wrap gap-4 border-t border-[var(--border)] pt-4 text-xs">
              <Link href="/legal/terms">Terms</Link>
              <Link href="/legal/privacy">Privacy</Link>
              <Link href="/legal/refunds">Refunds</Link>
              <Link href="/changelog">Changelog</Link>
              <a href="https://github.com/SrijithLegend/mcp-audit" rel="noreferrer noopener">
                GitHub
              </a>
              <a href="https://status.mcpaudit.dev" rel="noreferrer noopener">
                Status
              </a>
              <span>The CLI is MIT and does everything this does.</span>
            </footer>
          </div>
        </Providers>
      </body>
    </html>
  );
}
