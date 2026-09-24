"""The agent loop, offline, against a fake client. Shape only -- no model needed."""

from __future__ import annotations

import asyncio

import pytest

from mcp_audit.dryrun import canary, stub_result
from mcp_audit.errors import ApiError
from mcp_audit.harness import (
    MAX_TOKENS,
    build_request,
    normalize_for_api,
    run_arm,
    run_both,
    run_trial,
)
from mcp_audit.models import Inventory, Tool
from mcp_audit.sanitizer import sanitize
from tests.conftest import FakeClient, block, text


async def test_loop_records_calls_in_order_and_stops_on_a_text_turn(notes_inventory):
    fake = FakeClient(
        [
            [block("read_file", path="/etc/passwd")],
            [block("read_note", title="a"), block("read_note", title="b")],
            [text()],
        ]
    )
    trace = await run_trial(notes_inventory, side="real", trial=0, task="t", api=fake)
    assert [c.name for c in trace.calls] == ["read_file", "read_note", "read_note"]
    assert trace.calls[0].arguments == {"path": "/etc/passwd"}
    assert [c.index for c in trace.calls] == [0, 1, 2]
    assert [c.turn for c in trace.calls] == [0, 1, 1]
    assert trace.stop_reason == "no_tool_calls"
    assert len(fake.seen) == 3
    assert trace.api_calls == 3
    assert trace.input_tokens == 300 and trace.output_tokens == 60


async def test_every_tool_result_is_a_stub_and_no_argument_is_echoed(notes_inventory):
    fake = FakeClient([[block("read_file", path="/etc/passwd")], [text()]])
    await run_trial(notes_inventory, side="real", trial=0, task="t", api=fake)
    sent = fake.seen[-1]["messages"]
    results = [c for m in sent if isinstance(m["content"], list) for c in m["content"] if isinstance(c, dict)]
    assert len(results) == 1
    assert results[0]["content"] == stub_result("read_file", 0, "canary")
    assert "/etc/passwd" not in str(results)


async def test_canary_index_matches_what_features_recomputes(notes_inventory):
    fake = FakeClient([[block("read_file", path="/x")], [block("read_note", title="a")], [text()]])
    await run_trial(notes_inventory, side="real", trial=0, task="t", api=fake)
    served = [
        c["content"]
        for m in fake.seen[-1]["messages"]
        if isinstance(m["content"], list)
        for c in m["content"]
        if isinstance(c, dict)
    ]
    assert canary("read_file", 0) in served[0]
    assert canary("read_note", 1) in served[1]


async def test_a_model_that_never_stops_is_capped(notes_inventory):
    fake = FakeClient([[block("read_file", path="/x")] for _ in range(20)])
    trace = await run_trial(notes_inventory, side="real", trial=0, task="t", api=fake, max_turns=3)
    assert len(trace.calls) == 3
    assert trace.stop_reason == "max_turns"


async def test_each_trial_starts_from_a_clean_conversation(notes_inventory):
    fake = FakeClient(per_trial=[[block("read_file", path="/x")], [text()]])
    traces = await run_arm(notes_inventory, side="real", trials=3, task="t", api=fake)
    assert len(traces) == 3
    assert all(len(t.calls) == 1 for t in traces)
    assert [t.trial for t in traces] == [0, 1, 2]
    firsts = [kw for kw in fake.seen if len(kw["messages"]) == 1]
    assert len(firsts) == 3, "trial history leaked between trials"


async def test_both_arms_run_with_the_same_scaffolding(notes_inventory):
    fake = FakeClient(per_trial=[[text()]])
    real, san = await run_both(notes_inventory, sanitize(notes_inventory), trials=2, task="t", api=fake)
    assert [t.side for t in real] == ["real", "real"]
    assert [t.side for t in san] == ["sanitized", "sanitized"]
    payloads = {
        frozenset((k, str(v)) for k, v in kw.items() if k in ("model", "max_tokens")) for kw in fake.seen
    }
    assert len(payloads) == 1


async def test_escalated_trials_do_not_reuse_trial_numbers(notes_inventory):
    fake = FakeClient(per_trial=[[text()]])
    first = await run_arm(notes_inventory, side="real", trials=2, task="t", api=fake)
    second = await run_arm(notes_inventory, side="real", trials=2, first_trial=2, task="t", api=fake)
    assert [t.trial for t in first + second] == [0, 1, 2, 3]


async def test_an_api_error_fails_one_trial_not_the_scan(notes_inventory):
    class Flaky(FakeClient):
        async def create(self, **kwargs):
            raise RuntimeError("503 overloaded")

    trace = await run_trial(notes_inventory, side="real", trial=0, task="t", api=Flaky())
    assert trace.stop_reason == "api_error"
    assert "503" in (trace.error or "")


async def test_an_auth_error_aborts_the_scan(notes_inventory):
    class Unauthorized(FakeClient):
        async def create(self, **kwargs):
            raise type("AuthenticationError", (Exception,), {})("bad key")

    with pytest.raises(ApiError, match="rejected the API key"):
        await run_trial(notes_inventory, side="real", trial=0, task="t", api=Unauthorized())


def test_request_shape():
    inv = Inventory(instructions="hello", tools=[Tool(name="a", description="d")])
    payload, _ = build_request(inv, "task")
    assert payload["max_tokens"] == MAX_TOKENS
    assert payload["messages"] == [{"role": "user", "content": "task"}]
    assert payload["system"][0]["text"].endswith("hello")
    assert payload["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_normalize_repairs_names_and_schemas():
    inv = Inventory(
        tools=[
            Tool(name="mcp.notes/read", description="d", input_schema={"type": "string"}),
            Tool(name="mcp_notes_read", description="d"),
            Tool(name="x" * 200, description="d"),
        ]
    )
    tools, name_map = normalize_for_api(inv)
    assert all(len(t["name"]) <= 64 for t in tools)
    assert all(t["input_schema"]["type"] == "object" for t in tools)
    assert all(isinstance(t["input_schema"]["properties"], dict) for t in tools)
    assert len({t["name"] for t in tools}) == 3, "collisions must be broken, not merged"
    # reversible: the trace has to report the server's real names
    assert name_map[tools[0]["name"]] == "mcp.notes/read"
    assert set(name_map.values()) == {"mcp.notes/read", "mcp_notes_read", "x" * 200}


def test_normalization_is_identical_on_both_arms():
    inv = Inventory(
        instructions="p",
        tools=[Tool(name="a.b", description="prose", input_schema={"type": "object", "properties": {}})],
    )
    real, real_map = normalize_for_api(inv)
    clean, clean_map = normalize_for_api(sanitize(inv))
    assert real_map == clean_map
    assert [t["name"] for t in real] == [t["name"] for t in clean]


async def test_traces_map_api_names_back_to_server_names():
    inv = Inventory(tools=[Tool(name="mcp.notes/read", description="d")])
    sent, _ = normalize_for_api(inv)
    fake = FakeClient([[block(sent[0]["name"], title="a")], [text()]])
    trace = await run_trial(inv, side="real", trial=0, task="t", api=fake)
    assert trace.calls[0].name == "mcp.notes/read"


def test_run_arm_is_concurrent_but_bounded(notes_inventory):
    """Four in flight by default: enough to be fast, few enough to stay polite."""
    live = 0
    peak = 0

    class Counting(FakeClient):
        async def create(self, **kwargs):
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.01)
            live -= 1
            return await super().create(**kwargs)

    asyncio.run(run_arm(notes_inventory, side="real", trials=8, task="t", api=Counting()))
    assert 1 < peak <= 4
