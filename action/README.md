# mcp-audit GitHub Action

Confirms whether an MCP server's prose steers a model, uploads SARIF to code scanning,
and fails the job on a confirmed finding.

```yaml
permissions:
  contents: read
  security-events: write     # for the SARIF upload
  pull-requests: write       # only if comment: true

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
          api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

Remote server instead:

```yaml
        with:
          url: https://example.com/mcp
          header: |
            Authorization: Bearer ${{ secrets.MCP_TOKEN }}
          api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

Hosted (no LLM key of your own — we meter it):

```yaml
        with:
          command: npx -y @some/mcp-server
          cloud-token: ${{ secrets.MCP_AUDIT_TOKEN }}
```

## Notes

- `command` **runs the server on the runner.** That is the only way to read a stdio
  server's inventory. Tools are never executed.
- The audited server gets a minimal environment: pass what it needs with `env:`
  (`K=V` per line). The runner's other secrets — including `api-key` — are not passed
  to it.
- `max-cost` is a hard stop. The job fails rather than overspending.
- Outputs: `verdict`, `report` (JSON path), `cost-usd`.
- Scanning the same server on every push costs money for no new information. Prefer
  `on: schedule` plus `on: pull_request` with a path filter on your MCP config.
