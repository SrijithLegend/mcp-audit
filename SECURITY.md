# Reporting a vulnerability in mcp-audit

**Do not open a public issue for a security problem.**

Report it privately through
[GitHub Security Advisories](https://github.com/SrijithLegend/mcp-audit/security/advisories/new),
or email **srijithshaibu@gmail.com** with `mcp-audit security` in the subject.

Please include: what you did, what happened, what you expected, the version
(`mcp-audit version`), and a minimal reproduction if you have one.

**What to expect:** acknowledgement within 72 hours, an assessment within 7 days, and a
fix released before public disclosure. We will credit you unless you ask us not to.

## Scope

In scope:

- The CLI and engine (`src/mcp_audit/`) — in particular anything that would let an
  audited MCP server read our environment, execute one of its own tools through us,
  or escape the dry-run stub.
- The hosted service (`cloud/`) and `mcpaudit.dev` — auth bypass, cross-organisation
  data access, SSRF through remote targets, billing bypass, secret exposure.
- Our GitHub Action (`action/`).

Out of scope:

- Findings that require the user to scan a server they already chose to run. Scanning a
  stdio server executes it locally; that is documented, intended, and stated in
  `--help`.
- Missing steering that we document as out of reach (tool and parameter *names*,
  `enum`/`const` values, injection through tool results). See "What this does NOT catch"
  in the README.
- Reports from automated scanners with no demonstrated impact.

## Vulnerabilities in servers we scan

If `mcp-audit` confirms steering in a third-party MCP server, we notify the maintainer
privately first and wait 30 days before naming the server publicly
(`docs/ROADMAP.md` §2.4). If you report such a server to us, please do the same.

The threat model and the controls we hold ourselves to are in
[`docs/SECURITY.md`](docs/SECURITY.md).
