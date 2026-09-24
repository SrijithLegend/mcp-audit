"""Run the benchmark over bench/servers.yaml and write bench/results.csv.

    uv run python bench/run.py --dry-run          # capture only, no model calls, free
    uv run python bench/run.py --max-total 5.00   # the real thing; costs money

Two rules this script enforces so a benchmark cannot turn into an incident:

1. A total spend ceiling across the whole run, checked before each server.
2. `--anonymise` (default on) writes `server-01` instead of the server's name, because
   naming a vulnerable server before its maintainer has been told is not something we
   get to undo (ROADMAP §2.4).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import dataclasses
import json
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp_audit.audit import audit, engine_version  # noqa: E402
from mcp_audit.capture.http import capture_http  # noqa: E402
from mcp_audit.capture.stdio import capture_stdio  # noqa: E402
from mcp_audit.errors import AuditError  # noqa: E402
from mcp_audit.harness import DEFAULT_TASK, MODEL, client  # noqa: E402
from mcp_audit.models import Report, Verdict  # noqa: E402

OUT = ROOT / "bench"
FIELDS = (
    "server",
    "source",
    "server_version",
    "tools",
    "inventory_sha256",
    "verdict",
    "signals",
    "trials",
    "model",
    "cost_usd",
    "seconds",
    "date",
    "error",
)


@dataclass
class Target:
    name: str
    command: str = ""
    url: str = ""
    task: str = ""
    note: str = ""
    #: "K=V;K2=V2" in the yaml. Read from *our* environment by name when the value is
    #: empty ("GITHUB_PERSONAL_ACCESS_TOKEN="), so a token never lands in a committed
    #: file. Nothing else is inherited (CLAUDE.md invariant 4).
    env: str = ""

    def env_pairs(self) -> dict[str, str]:
        import os

        out: dict[str, str] = {}
        for item in self.env.split(";"):
            if not item.strip():
                continue
            key, _, value = item.partition("=")
            resolved = value or os.environ.get(key.strip(), "")
            if resolved:
                out[key.strip()] = resolved
        return out


def load_targets(path: Path) -> list[Target]:
    """A 20-line loader instead of a yaml dependency (decision D2).

    Understands exactly the subset servers.yaml uses: a list of `- key: value` blocks,
    one line per key. Unknown keys are ignored rather than fatal -- a typo in a comment
    field should not stop a benchmark run -- and anything fancier than this (folded
    scalars, nesting) is not supported on purpose. If the file ever needs it, take the
    yaml dependency in bench/ only; the engine still must not have one.
    """
    fields = {f.name for f in dataclasses.fields(Target)}
    targets: list[Target] = []
    current: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split(" #", 1)[0].rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("- "):
            if current:
                targets.append(Target(**current))
            current = {}
            line = "  " + line[2:]
        key, _, value = line.strip().partition(":")
        if key.strip() in fields:
            current[key.strip()] = value.strip().strip('"')
    if current:
        targets.append(Target(**current))
    return targets


async def capture(target: Target):
    if target.url:
        return await capture_http(target.url)
    argv = shlex.split(target.command)
    inventory, _ = await capture_stdio(argv[0], argv[1:], env=target.env_pairs(), timeout=60.0)
    return inventory


def signal_summary(report: Report) -> str:
    return "; ".join(
        f"{f.signal.label()} {f.signal.real_hits}/{f.signal.n_real}v{f.signal.san_hits}/{f.signal.n_san}"
        for f in report.findings
        if f.verdict is not Verdict.CLEAN
    )


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", type=Path, default=OUT / "servers.yaml")
    ap.add_argument("--only", action="append", help="Run only these names, repeatable")
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--max-cost", type=float, default=0.50, help="Per server")
    ap.add_argument("--max-total", type=float, default=2.00, help="Whole run. A hard stop.")
    ap.add_argument("--dry-run", action="store_true", help="Capture only; no model calls")
    ap.add_argument("--anonymise", action="store_true", default=True)
    ap.add_argument(
        "--name-servers",
        dest="anonymise",
        action="store_false",
        help="Write real server names. Only after disclosure (ROADMAP §2.4).",
    )
    ap.add_argument("--out", type=Path, default=OUT / "results.csv")
    args = ap.parse_args()

    targets = [t for t in load_targets(args.file) if not args.only or t.name in args.only]
    api = None if args.dry_run else client()
    spent = 0.0
    rows = []

    for i, target in enumerate(targets, 1):
        label = target.name if not args.anonymise else f"server-{i:02d}"
        row = {
            "server": label,
            "source": target.url or target.command if not args.anonymise else "(withheld)",
            "trials": args.trials,
            "model": args.model,
            "date": time.strftime("%Y-%m-%d"),
            "error": "",
            "verdict": "",
            "signals": "",
            "cost_usd": 0.0,
            "seconds": 0.0,
            "tools": 0,
            "server_version": "",
            "inventory_sha256": "",
        }
        started = time.time()
        print(f"[{i}/{len(targets)}] {label} ...", flush=True)
        try:
            if spent >= args.max_total:
                raise AuditError(f"run budget ${args.max_total:.2f} reached; stopping")
            inventory = await capture(target)
            row["tools"] = len(inventory.tools)
            row["server_version"] = inventory.server_version or ""
            row["inventory_sha256"] = inventory.sha256()[:16]
            if not args.dry_run:
                report = await audit(
                    inventory,
                    api=api,
                    task=target.task or DEFAULT_TASK,
                    trials=args.trials,
                    model=args.model,
                    max_cost=min(args.max_cost, args.max_total - spent),
                    assume_yes=False,
                    interactive=False,
                )
                spent += report.usage.cost_usd
                row["verdict"] = report.verdict.value
                row["signals"] = signal_summary(report)
                row["cost_usd"] = round(report.usage.cost_usd, 4)
                (OUT / "reports").mkdir(exist_ok=True)
                (OUT / "reports" / f"{label}.json").write_text(
                    json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8"
                )
        except AuditError as exc:
            row["error"] = str(exc)[:200]
            print(f"    error: {exc}", flush=True)
        except Exception as exc:  # a benchmark must not die on one bad server
            row["error"] = f"{type(exc).__name__}: {exc}"[:200]
            print(f"    error: {row['error']}", flush=True)
        row["seconds"] = round(time.time() - started, 1)
        rows.append(row)
        print(f"    {row['verdict'] or 'captured'} ({row['tools']} tools, ${row['cost_usd']})", flush=True)

    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {args.out} — engine {engine_version()}, total ${spent:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
