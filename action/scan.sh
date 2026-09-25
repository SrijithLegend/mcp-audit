#!/usr/bin/env bash
# The Action's body. Kept out of action.yml so nothing user-supplied is ever
# interpolated into a shell command by the Actions templater: every input arrives
# as an environment variable and is passed to the CLI as a separate argv element.
set -uo pipefail

: "${INPUT_TRIALS:=5}"
: "${INPUT_MAX_COST:=1.00}"
: "${INPUT_FAIL_ON:=confirmed}"
: "${INPUT_SARIF:=mcp-audit.sarif}"

pkg="mcp-audit"
[ -n "${INPUT_VERSION:-}" ] && pkg="mcp-audit==${INPUT_VERSION}"

sources=0
[ -n "${INPUT_COMMAND:-}" ] && sources=$((sources + 1))
[ -n "${INPUT_URL:-}" ] && sources=$((sources + 1))
[ -n "${INPUT_INVENTORY:-}" ] && sources=$((sources + 1))
if [ "$sources" -ne 1 ]; then
  echo "::error::give exactly one of: command, url, inventory"
  echo "exit-code=2" >> "$GITHUB_OUTPUT"
  exit 2
fi

# The scan always runs here, on the caller's key. A cloud token only decides whether the
# finished report is also uploaded for history and monitoring.
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "::error::set api-key: the scan runs in this job, on your own Anthropic key"
  echo "exit-code=4" >> "$GITHUB_OUTPUT"
  exit 4
fi

args=(scan)
if [ -n "${INPUT_COMMAND:-}" ]; then
  # The command is a command line by nature; split it on whitespace only, and never
  # hand it to a shell.
  read -r -a parts <<< "$INPUT_COMMAND"
  args+=("${parts[@]}")
elif [ -n "${INPUT_URL:-}" ]; then
  args+=(--url "$INPUT_URL")
else
  args+=(--inventory "$INPUT_INVENTORY")
fi

args+=(--trials "$INPUT_TRIALS" --max-cost "$INPUT_MAX_COST" --fail-on "$INPUT_FAIL_ON")
args+=(--sarif "$INPUT_SARIF" --md mcp-audit.md --json)
[ -n "${INPUT_TASK:-}" ] && args+=(--task "$INPUT_TASK")
[ -n "${INPUT_MODEL:-}" ] && args+=(--model "$INPUT_MODEL")
[ -n "${MCP_AUDIT_TOKEN:-}" ] && args+=(--push)

while IFS= read -r pair; do
  [ -n "$pair" ] && args+=(--env "$pair")
done <<< "${INPUT_ENV:-}"

while IFS= read -r header; do
  [ -n "$header" ] && args+=(--header "$header")
done <<< "${INPUT_HEADER:-}"

echo "running: mcp-audit ${args[*]:0:2} ... (${#args[@]} arguments)"
uvx --from "$pkg" mcp-audit "${args[@]}" > mcp-audit.json
code=$?

verdict=$(python3 -c 'import json,sys;print(json.load(open("mcp-audit.json")).get("verdict","ERROR"))' 2>/dev/null || echo ERROR)
cost=$(python3 -c 'import json,sys;print(json.load(open("mcp-audit.json")).get("usage",{}).get("cost_usd",0))' 2>/dev/null || echo 0)

{
  echo "verdict=$verdict"
  echo "report=mcp-audit.json"
  echo "cost-usd=$cost"
  echo "exit-code=$code"
} >> "$GITHUB_OUTPUT"

{
  echo "## mcp-audit: $verdict"
  echo
  [ -f mcp-audit.md ] && cat mcp-audit.md
} >> "$GITHUB_STEP_SUMMARY"

# Never fail here: action.yml decides, so the SARIF upload and PR comment steps
# still run on a confirmed finding.
exit 0
