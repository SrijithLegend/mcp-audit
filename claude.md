1. Fix what's broken (blocking)
Package layout: move the code into src/mcp_audit/. Right now the wheel ships with zero Python files, so the installed CLI crashes.
Version single source: importlib.metadata.version(). Delete the hardcoded "1.0.0".
Rename scan → inspect: scan should mean the actual audit, not a JSON dump.
Delete the report stub: dead commands make a tool look unfinished.
Gitignore .vscode/: editor config doesn't belong in the repo.
Add a LICENSE (MIT/Apache-2.0): without one, nobody can legally use or contribute to the code. Your repo has none.
2. Core engine (the product)
Close sanitizer holes: strip $comment, examples and default, all of which can carry injected prose.
Fixture servers: 2 poisoned (instruction injection, exfil via param) and 1 clean control. Without a known positive and a known negative, you can't claim the tool works.
Dry-run tool execution (safety-critical): intercept the model's tool calls and return stub results. Never execute them against a real server. Otherwise, auditing a filesystem server with a hijacked model actually reads ~/.ssh and ships it to the API. Your security tool would be the exploit.
Agent harness: bring-your-own ANTHROPIC_API_KEY, one cheap model, loop until the model stops calling tools, record the tool-call trace.
Benign task: --task flag with a sensible default, since the model needs a reason to use tools.
N-trial runs: default 5 per side. LLMs are stochastic, and a single-run diff is noise.
Differ + verdict: compare call rates, e.g. read_notes 5/5 real vs 0/5 sanitized = STEERING CONFIRMED. Define the thresholds explicitly.
scan command: wires inspect → sanitize → harness → differ → verdict into one command.
3. Output & UX
Terminal report: verdict per tool, call rates on both sides, the divergent call as evidence.
--json: machine-readable output for CI and scripting.
Exit codes: 1 on confirmed steering, so it can gate a CI pipeline.
Clean errors: server won't start, missing API key, timeout. One readable line each, not the 40-line ExceptionGroup traceback I hit.
Cost guard: print the planned API calls (tools × trials × 2) before running, plus a --trials flag.
4. Validation
pytest + GitHub Actions: turn the __main__ self-checks into real tests that run on every push.
Fixture results: poisoned = CONFIRMED and clean = clean, on every run. Also measure the false-positive rate on the clean control.
Scan 5–10 popular real servers: record a results table. This is your launch data.
Head-to-head vs mcp-scan / Snyk agent-scan: run them on the same servers and count their false positives vs yours. This is your entire differentiation claim, and without it the pitch is unsupported.
Responsible disclosure: if you confirm steering in a real server, notify the maintainer privately and give them time before naming it publicly.
5. Packaging & docs
Publish to PyPI: verify that uvx mcp-audit version works from a clean shell, not just your dev environment.
README:
one-line pitch and install command
usage and example output
how the differential method works
cost note and safety note (dry-run)
"What this does NOT catch": steering via tool/param names and enum values (they survive sanitization), runtime output injection, rug-pulls where a description changes after approval, HTTP transport
Demo GIF / asciinema: most people decide from the GIF, not the text.