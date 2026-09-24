import Link from "next/link";

import { Card } from "@/components/ui";

export default function Settings() {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Settings</h1>
      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Tokens">
          <p className="dim text-xs">
            <Link href="/app/settings/tokens">CI credentials</Link> for pipelines and{" "}
            <code>mcp-audit login</code>.
          </p>
        </Card>
        <Card title="Billing">
          <p className="dim text-xs">
            <Link href="/app/settings/billing">Plan, usage and payment method.</Link>
          </p>
        </Card>
        <Card title="Organisation">
          <p className="dim text-xs">
            <Link href="/app/settings/org">Members, roles and seats.</Link>
          </p>
        </Card>
      </div>
    </div>
  );
}
