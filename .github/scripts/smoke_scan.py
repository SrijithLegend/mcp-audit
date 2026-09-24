"""Release smoke test: run the whole pipeline from an installed wheel, for free.

A wheel that imports is not a wheel that works. This drives `audit()` end to end
against a captured inventory with a scripted fake model, so the release gate covers
the pipeline without needing a key or spending anything.

    python .github/scripts/smoke_scan.py path/to/inventory.json
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

from mcp_audit.audit import audit
from mcp_audit.models import Inventory, Verdict


class FakeModel:
    """Calls read_file on the arm that still has the server's prose, nothing on the other."""

    @property
    def messages(self) -> FakeModel:
        return self

    async def create(self, **kwargs: Any) -> NS:
        system = kwargs["system"][0]["text"]
        poisoned = len(system) > 200 or "read_file" in system
        first_turn = len(kwargs["messages"]) == 1
        if poisoned and first_turn:
            content = [NS(type="tool_use", id="t1", name="read_file", input={"path": "/etc/passwd"})]
        else:
            content = [NS(type="text", text="done")]
        return NS(
            content=content,
            usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0),
            stop_reason="end_turn",
        )

    async def count_tokens(self, **_kwargs: Any) -> NS:
        return NS(input_tokens=100)


async def main(path: str) -> int:
    inventory = Inventory.model_validate_json(Path(path).read_text(encoding="utf-8"))
    report = await audit(inventory, api=FakeModel(), trials=3, escalate=False, interactive=False)
    print(f"verdict={report.verdict.value} tools={len(inventory.tools)} traces={len(report.traces)}")
    assert report.verdict in set(Verdict), report.verdict
    assert len(report.traces) == 6, report.traces
    assert report.inventory_sha256 == inventory.sha256()
    print("smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1])))
