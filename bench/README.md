# bench/

Real-server results and the head-to-head with static scanners. **Nothing in here is
published with a server's name attached until responsible disclosure has run**
(ROADMAP §2.4) — `run.py` anonymises by default and you have to pass `--name-servers`
to change that.

## Running it

```bash
# free: capture inventories only, no model calls
uv run python bench/run.py --dry-run

# the real thing. ASK SRIJITH FIRST -- this spends money (CLAUDE.md).
uv run python bench/run.py --trials 5 --max-cost 0.50 --max-total 5.00

# then the comparison
uv run python bench/headtohead.py \
  --scanner "uvx mcp-scan@latest scan --json {target}" \
  --scanner-name mcp-scan --scanner-version X.Y.Z
```

Outputs: `results.csv`, `reports/<server>.json` (full reports), `headtohead.csv`,
`raw/<server>.txt` (the other tool's unedited output).

## Fixture gate (Gate 1)

```bash
uv run pytest -q -m gate          # 10 runs per fixture, ~$5-10. Ask first.
```

Gate 1 passes when every poisoned fixture is CONFIRMED in ≥ 9/10 runs and both control
fixtures are CONFIRMED in 0/10. Record the numbers in `fixtures.md` with the date and
the engine version. **If a poisoned fixture fails, fix the engine — do not lower the
threshold** (CLAUDE.md invariant 6).

## Why the false-positive column is the headline

Static scanners (Invariant/Snyk `mcp-scan`, `agent-scan`) read the text and flag what
looks dangerous. That finds real problems, and it also fires on `benign_verbose.py` —
an honest server whose descriptions say "ALWAYS call list_notes first", because that is
genuinely how you use it. Our claim is not "we find more"; it is **"we cry wolf less,
on the same servers, and we show you the behaviour that proves it"**. So the number
that matters is false positives on manually-reviewed-clean servers, and
`headtohead.py` prints exactly that.

Be fair in the other direction too: `their_only` counts servers they flagged and we did
not. Some of those are real and out of our reach by construction — steering through tool
*names*, `enum` values, or a known-bad publisher. Report them.
