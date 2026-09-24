"""The data that crosses boundaries: inventories, traces, findings, reports.

Two of these are wire formats with a version string, because other people's
pipelines parse them: `Inventory` (what the CLI captures and the Cloud accepts)
and `Report` (what CI reads). Add fields; never repurpose one.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

INVENTORY_FORMAT: Final = "mcp-audit/inventory@1"
REPORT_FORMAT: Final = "mcp-audit/report@1"


def _now() -> datetime:
    return datetime.now(UTC)


class Tool(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})

    def param_names(self) -> list[str]:
        props = self.input_schema.get("properties")
        return list(props) if isinstance(props, dict) else []

    def required(self) -> list[str]:
        req = self.input_schema.get("required")
        return [r for r in req if isinstance(r, str)] if isinstance(req, list) else []


class Inventory(BaseModel):
    """Everything an MCP server tells a model before anything is called.

    This is the interchange format between the CLI and the Cloud: the CLI captures
    it locally (it may have to run a stdio server to do that), the Cloud only ever
    receives it.
    """

    model_config = ConfigDict(extra="ignore")

    format: Literal["mcp-audit/inventory@1"] = INVENTORY_FORMAT
    instructions: str = ""
    tools: list[Tool] = Field(default_factory=list)
    server_name: str | None = None
    server_version: str | None = None
    protocol_version: str | None = None
    captured_at: datetime = Field(default_factory=_now)
    source: str = ""

    @classmethod
    def from_initialize(cls, init: Any, tools: list[Tool], source: str) -> Inventory:
        """Build from an MCP InitializeResult, whatever it calls its fields.

        The SDK has renamed these between protocol revisions (`serverInfo` ->
        `server_info`), so we read both spellings rather than pin a version.
        """
        server = getattr(init, "server_info", None) or getattr(init, "serverInfo", None)
        protocol = getattr(init, "protocol_version", None) or getattr(init, "protocolVersion", None)
        return cls(
            instructions=getattr(init, "instructions", None) or "",
            tools=tools,
            server_name=getattr(server, "name", None) or None,
            server_version=getattr(server, "version", None) or None,
            protocol_version=str(protocol) if protocol else None,
            source=source,
        )

    def sha256(self) -> str:
        """Hash of what the server *says*, not of when we looked.

        `captured_at` and `source` are excluded on purpose: the same server
        captured twice must hash identically or the scan cache and the rug-pull
        monitor both break. A version bump does change the hash -- that is a
        change worth re-scanning.
        """
        payload = self.model_dump(
            mode="json",
            include={"instructions", "tools", "server_name", "server_version"},
        )
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def schema_nodes(self) -> int:
        """Count of dict/list nodes across all schemas -- an abuse limit for Cloud."""
        return sum(_count_nodes(t.input_schema) for t in self.tools)


def _count_nodes(node: Any) -> int:
    if isinstance(node, dict):
        return 1 + sum(_count_nodes(v) for v in node.values())
    if isinstance(node, list):
        return 1 + sum(_count_nodes(v) for v in node)
    return 0


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    turn: int = 0
    index: int = 0


StopReason = Literal["no_tool_calls", "max_turns", "api_error"]


class Trace(BaseModel):
    """One trial on one arm: what the model called, in order, and what it cost."""

    side: Literal["real", "sanitized"]
    trial: int
    calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: StopReason = "no_tool_calls"
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    api_calls: int = 0
    error: str | None = None


class Verdict(StrEnum):
    CONFIRMED = "CONFIRMED"
    SUSPECTED = "SUSPECTED"
    CLEAN = "CLEAN"
    INCONCLUSIVE = "INCONCLUSIVE"


#: worst-first, so `max(verdicts, key=SEVERITY.get)` picks the server verdict
SEVERITY: dict[Verdict, int] = {
    Verdict.CLEAN: 0,
    Verdict.INCONCLUSIVE: 1,
    Verdict.SUSPECTED: 2,
    Verdict.CONFIRMED: 3,
}


class Signal(BaseModel):
    """One 2x2 comparison: how often a behaviour showed up on each arm.

    `kind` is what was measured, `detail` narrows it (a detector id for
    `sensitive`, a parameter name for `optional_populated`).
    """

    tool: str
    kind: Literal["called", "called_first", "sensitive", "canary_flow", "optional_populated"]
    detail: str = ""
    security_relevant: bool = False
    real_hits: int = 0
    san_hits: int = 0
    n_real: int = 0
    n_san: int = 0
    p_raw: float = 1.0
    p_adj: float = 1.0

    @property
    def real_rate(self) -> float:
        return self.real_hits / self.n_real if self.n_real else 0.0

    @property
    def san_rate(self) -> float:
        return self.san_hits / self.n_san if self.n_san else 0.0

    @property
    def delta(self) -> float:
        return self.real_rate - self.san_rate

    @property
    def direction(self) -> Literal["toward", "away"]:
        """Steering *toward* a call, or away from one ("never call audit_log")."""
        return "toward" if self.delta >= 0 else "away"

    def label(self) -> str:
        return f"{self.tool}:{self.kind}" + (f"[{self.detail}]" if self.detail else "")


class Evidence(BaseModel):
    """What a maintainer needs to act: the call, and where to find it."""

    call: ToolCall | None = None
    trial: int | None = None
    sanitized_summary: str = ""


class Finding(BaseModel):
    signal: Signal
    verdict: Verdict
    evidence: Evidence | None = None


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    api_calls: int = 0
    cost_usd: float = 0.0


class Report(BaseModel):
    """The artifact. A verdict with no task, model or trial count attached is
    not reproducible six months later, so all of it rides along."""

    model_config = ConfigDict(extra="ignore")

    format: Literal["mcp-audit/report@1"] = REPORT_FORMAT
    engine_version: str = ""
    created_at: datetime = Field(default_factory=_now)

    target: str = ""
    inventory_sha256: str = ""
    server_name: str | None = None
    model: str = ""
    task: str = ""
    trials: int = 0
    stub_mode: str = "canary"
    escalated: bool = False
    #: None means "the API default" (1.0). We never set it: stochasticity is what the
    #: trials sample, so pinning it would measure one draw instead of a distribution.
    temperature: float | None = None

    verdict: Verdict = Verdict.CLEAN
    tool_verdicts: dict[str, Verdict] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)
    traces: list[Trace] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    stripped_diff: str = ""
    notes: list[str] = Field(default_factory=list)

    def failed(self, fail_on: str = "confirmed") -> bool:
        if self.verdict is Verdict.CONFIRMED:
            return True
        return fail_on == "suspected" and self.verdict is Verdict.SUSPECTED


LIMITS = (
    "Not caught: steering via tool or parameter names and enum/const values (they must "
    "survive sanitization); injection through tool *results* (we never execute tools); "
    "a server that changes between scans; steering specific to another model.",
)
