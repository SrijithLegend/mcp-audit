# Fixture gate results (Gate 1)

Run: `uv run pytest -q -m gate` (10 scans per fixture, defaults, ~$5-10).

Fill this in from the run, with the engine version and the date. An empty table means
Gate 1 has not been run yet -- it needs `ANTHROPIC_API_KEY` and Srijith's go-ahead,
because it spends real money (CLAUDE.md).

| Fixture | Expected | CONFIRMED | Median $/scan | Engine | Date |
|---|---|---|---|---|---|
| `poisoned_instructions.py` | >= 9/10 | — | — | — | — |
| `poisoned_param.py` | >= 9/10 | — | — | — | — |
| `poisoned_tool_desc.py` | >= 9/10 | — | — | — | — |
| `poisoned_nested.py` | >= 9/10 | — | — | — | — |
| `poisoned_suppress.py` | >= 9/10 | — | — | — | — |
| `clean.py` | 0/10 | — | — | — | — |
| `benign_verbose.py` | 0/10 | — | — | — | — |

## Notes for whoever runs it

- `poisoned_suppress.py` steers *away* from a tool. Its finding is
  `audit_log:called` with `direction=away`, which is behavioural, not security-relevant
  by the current rules -- so it can legitimately land on SUSPECTED rather than CONFIRMED.
  If it does, that is a real result to discuss, not a bug to paper over: either
  suppression of an audit tool should count as security-relevant (a rule change, which
  needs Srijith), or the gate for this fixture is SUSPECTED.
- The stub mode default (`canary`) was chosen from ROADMAP §1.3's expectation. If
  `inert` turns out to score better on this matrix, record both columns before changing
  the default.
- Record the median cost per scan: Phase 5 pricing is computed from it, and the plan
  table in ROADMAP §5.1 is explicitly not to be shipped without this number.
