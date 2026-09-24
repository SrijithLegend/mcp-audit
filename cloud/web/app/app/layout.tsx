import Link from "next/link";
import type { ReactNode } from "react";

/** The signed-in shell. Authorisation is the API's job; this is just navigation. */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-4">
      <nav aria-label="App" className="dim flex flex-wrap gap-4 border-b border-[var(--border)] pb-2 text-xs">
        <Link href="/app">Scans</Link>
        <Link href="/app/scans/new">New scan</Link>
        <Link href="/app/targets">Targets</Link>
        <Link href="/app/monitors">Monitors</Link>
        <Link href="/app/settings">Settings</Link>
      </nav>
      {children}
    </div>
  );
}
