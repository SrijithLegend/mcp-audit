# PROGRESS

Claude Code: update this at the end of every session. Srijith ticks gates.

## Current phase: 0 — Hygiene

## Gates
- [ ] Gate 0 — CI green, invariant tests, self-checks migrated
- [ ] Gate 1 — fixtures: poisoned ≥ 9/10 CONFIRMED, clean + benign_verbose 0/10 CONFIRMED (live, ~$5–10)
- [ ] Gate 2 — PyPI + Action + benchmark + head-to-head published; launched
- [ ] Gate 3 — Cloud backend + security suites
- [ ] Gate 4 — Frontend e2e, a11y, CSP clean
- [ ] Gate 5 — Billing lifecycle in test mode
- [ ] Gate 7 — Launch checklist (docs/SECURITY.md) 100 %

## Done
- Package layout, LICENSE, sanitizer + 3 fixtures, dry-run stubs, single-trial harness,
  `inspect` / `trial` / `version` (as of `adb5d51`, 2026-09-22)

## Next
- Phase 0 items 1–7 (docs/ROADMAP.md)

## Measured numbers
- (fill in: cost/scan, FP rate, gate results, dates)

## Open questions for Srijith
- Final plan prices/limits (after Gate 1 cost numbers)
- `cloud/` license: AGPL in this repo vs private repo (D7)
