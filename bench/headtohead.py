"""Head-to-head against the static scanners (ROADMAP §2.2).

    uv run python bench/headtohead.py --scanner "uvx mcp-scan@latest scan --json {target}"

The headline metric is **false positives on servers where manual review finds no
steering** -- the fixtures `clean.py` and `benign_verbose.py`, plus any benchmark server
marked clean by hand. That is the number the product is sold on, so it is the number we
measure most carefully, and we record their tool version and the date so the comparison
can be reproduced or disputed.

Be fair. This script has a `their_only` column and it is meant to be populated: static
scanners catch things we cannot (steering via tool *names*, enum values, known-bad
hashes), and hiding that would make the benchmark worthless.
"""

from __future__ import annotations

import argparse
import csv
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "bench"

#: Servers a human has read end to end and found no steering in. Edit deliberately:
#: every name here is a claim that a flag against it is a false positive.
MANUALLY_CLEAN = {
    "fixture-clean",
    "fixture-benign-verbose",
    "time",
    "sequentialthinking",
}

FIELDS = (
    "server",
    "manually_clean",
    "ours",
    "theirs_flags",
    "theirs_verdict",
    "agreement",
    "our_false_positive",
    "their_false_positive",
    "their_only",
    "scanner",
    "scanner_version",
    "date",
)


def run_scanner(template: str, target: str, timeout: float = 300.0) -> tuple[str, int]:
    """Run the other tool exactly as a user would, and keep its raw output."""
    command = shlex.split(template.replace("{target}", target))
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return (done.stdout or done.stderr), done.returncode
    except subprocess.TimeoutExpired:
        return "(timeout)", 124
    except FileNotFoundError:
        return "(scanner not installed)", 127


def count_flags(output: str) -> tuple[int, str]:
    """Flags and a one-word verdict, from JSON if the tool emits it, else by keyword."""
    try:
        parsed = json.loads(output)
        issues = parsed if isinstance(parsed, list) else parsed.get("issues") or parsed.get("results") or []
        return len(issues), ("flagged" if issues else "clean")
    except (ValueError, AttributeError):
        lowered = output.lower()
        hits = sum(lowered.count(word) for word in ("vulnerab", "suspicious", "injection", "risk:"))
        return hits, ("flagged" if hits else "clean")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scanner", required=True, help="Command template with {target}")
    ap.add_argument("--scanner-name", default="")
    ap.add_argument("--scanner-version", default="", help="Record it; the comparison ages")
    ap.add_argument("--ours", type=Path, default=OUT / "results.csv", help="Output of bench/run.py")
    ap.add_argument("--out", type=Path, default=OUT / "headtohead.csv")
    args = ap.parse_args()

    if not args.ours.exists():
        print(f"{args.ours} missing -- run bench/run.py first", file=sys.stderr)
        return 2

    with args.ours.open(encoding="utf-8") as fh:
        ours = list(csv.DictReader(fh))

    rows = []
    for row in ours:
        target = row["source"]
        if target in ("", "(withheld)"):
            print(f"skipping {row['server']}: source withheld, cannot run the other scanner")
            continue
        output, _ = run_scanner(args.scanner, target)
        flags, their_verdict = count_flags(output)
        clean = row["server"] in MANUALLY_CLEAN
        our_verdict = row["verdict"] or "ERROR"
        rows.append(
            {
                "server": row["server"],
                "manually_clean": clean,
                "ours": our_verdict,
                "theirs_flags": flags,
                "theirs_verdict": their_verdict,
                "agreement": (our_verdict in ("CONFIRMED", "SUSPECTED")) == (their_verdict == "flagged"),
                "our_false_positive": clean and our_verdict == "CONFIRMED",
                "their_false_positive": clean and their_verdict == "flagged",
                "their_only": their_verdict == "flagged" and our_verdict in ("CLEAN", "INCONCLUSIVE"),
                "scanner": args.scanner_name or shlex.split(args.scanner)[0],
                "scanner_version": args.scanner_version,
                "date": time.strftime("%Y-%m-%d"),
            }
        )
        (OUT / "raw").mkdir(exist_ok=True)
        (OUT / "raw" / f"{row['server']}.txt").write_text(output[:200_000], encoding="utf-8")

    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    clean_rows = [r for r in rows if r["manually_clean"]]
    print(f"\nwrote {args.out}")
    if clean_rows:
        print(
            f"false positives on {len(clean_rows)} manually-clean servers: "
            f"ours {sum(r['our_false_positive'] for r in clean_rows)}, "
            f"theirs {sum(r['their_false_positive'] for r in clean_rows)}"
        )
    print(f"they flagged something we did not on {sum(r['their_only'] for r in rows)} servers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
