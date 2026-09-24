import type { Metadata } from "next";
import Link from "next/link";

import { Card } from "@/components/ui";

export const metadata: Metadata = { title: "Docs" };

const QUICKSTART = `# 1. install (free, MIT, no account)
uv tool install mcp-audit
export ANTHROPIC_API_KEY=sk-ant-...

# 2. scan a server. this RUNS it locally -- only scan servers you'd run anyway
mcp-audit scan npx -y @some/mcp-server

# 3. see what sanitization removed, before you believe the verdict
mcp-audit sanitize npx -y @some/mcp-server`;

const CLOUD = `# capture locally (stdio needs your machine), scan on ours
mcp-audit inspect npx -y @some/mcp-server --out inventory.json
# then upload inventory.json at /app/scans/new, or:
mcp-audit login --token mcpa_...
mcp-audit scan npx -y @some/mcp-server --cloud`;

const CI = `permissions:
  contents: read
  security-events: write

jobs:
  mcp-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: SrijithLegend/mcp-audit/action@v0
        with:
          command: npx -y @some/mcp-server
          trials: 5
          max-cost: "0.50"
          fail-on: confirmed
          api-key: \${{ secrets.ANTHROPIC_API_KEY }}
          # or: cloud-token: \${{ secrets.MCP_AUDIT_TOKEN }}`;

const API = `# every hosted feature is an API call; the web app is just a client
curl -H "Authorization: Bearer mcpa_..." https://api.mcpaudit.dev/v1/me

curl -X POST https://api.mcpaudit.dev/v1/scans \
  -H "Authorization: Bearer mcpa_..." \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "content-type: application/json" \
  -d @<(jq '{inventory: .}' inventory.json)

curl -H "Authorization: Bearer mcpa_..." \
  https://api.mcpaudit.dev/v1/scans/<id>/report.sarif`;

export default function Docs() {
  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-xl font-semibold">Docs</h1>
        <p className="dim max-w-2xl text-sm">
          Everything here works with the free CLI. The hosted service adds history, monitoring and
          teams; it does not add verdicts.
        </p>
      </header>

      <Card title="Quickstart">
        <pre className="hostile surface rounded p-3 text-xs">{QUICKSTART}</pre>
        <p className="dim mt-2 text-xs">
          Exit codes: 0 clean or inconclusive, 1 confirmed, 2 usage, 3 capture failed, 4 API or
          key, 5 over the cost ceiling.
        </p>
      </Card>

      <Card title="Hosted scans">
        <pre className="hostile surface rounded p-3 text-xs">{CLOUD}</pre>
        <p className="dim mt-2 text-xs">
          Capture always happens on your side for stdio servers, because capturing means running
          them. We accept the resulting inventory, or an <code>https://</code> endpoint we can fetch
          ourselves.
        </p>
      </Card>

      <Card title="CI">
        <pre className="hostile surface rounded p-3 text-xs">{CI}</pre>
        <p className="dim mt-2 text-xs">
          Scanning on every push costs money for no new information. Prefer a schedule plus a path
          filter on the file that pins your MCP servers.
        </p>
      </Card>

      <Card title="API">
        <pre className="hostile surface rounded p-3 text-xs">{API}</pre>
        <p className="dim mt-2 text-xs">
          OpenAPI at <code>/openapi.json</code>. Cursor pagination, <code>Idempotency-Key</code> on
          scan creation, and RFC 9457 problem+json errors whose <code>type</code> slug is the stable
          part.
        </p>
      </Card>

      <Card title="Methodology">
        <p className="dim text-sm">
          How a verdict is computed — features, Fisher exact, Holm correction, the global-shift
          control and adaptive escalation — is written out in{" "}
          <a
            href="https://github.com/SrijithLegend/mcp-audit/blob/main/docs/methodology.md"
            rel="noreferrer noopener"
          >
            docs/methodology.md
          </a>
          , in enough detail to argue with. If you think the statistics are wrong, the fixtures in{" "}
          <code>fixtures/</code> are how you would show it.
        </p>
        <p className="dim mt-2 text-sm">
          The limits are on the <Link href="/">front page</Link> and in every report, not in a
          footnote.
        </p>
      </Card>
    </div>
  );
}
