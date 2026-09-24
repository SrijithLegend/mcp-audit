"""Capture, against the real fixture servers. Spawns processes; no model calls."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time

import pytest

from mcp_audit.capture.http import capture_http, http_client, parse_headers
from mcp_audit.capture.paginate import MAX_TOOLS
from mcp_audit.capture.stdio import capture_stdio, parse_env
from mcp_audit.errors import CaptureError
from mcp_audit.models import Inventory
from mcp_audit.sanitizer import sanitize
from tests.conftest import FIXTURES

POISONED = (
    "poisoned_instructions",
    "poisoned_param",
    "poisoned_tool_desc",
    "poisoned_nested",
    "poisoned_suppress",
)
CLEAN = ("clean", "benign_verbose")


def grab(name: str) -> Inventory:
    inventory, _ = asyncio.run(capture_stdio(sys.executable, [str(FIXTURES / f"{name}.py")]))
    return inventory


@pytest.fixture(scope="module")
def captured() -> dict[str, Inventory]:
    return {name: grab(name) for name in POISONED + CLEAN}


def test_every_fixture_captures(captured):
    for name, inv in captured.items():
        assert inv.tools, name
        assert inv.server_name, name
        assert inv.protocol_version, name
        assert inv.source.startswith("stdio: "), name
        assert inv.sha256() != grab_sha_of_nothing(), name


def grab_sha_of_nothing() -> str:
    return Inventory().sha256()


def test_the_injections_are_actually_captured(captured):
    """A scanner that never sees the payload cannot confirm anything."""
    assert "/etc/passwd" in captured["poisoned_instructions"].instructions
    for name in ("poisoned_param", "poisoned_tool_desc", "poisoned_nested"):
        assert "/etc/passwd" in json.dumps([t.model_dump() for t in captured[name].tools]), name
    assert "Never call audit_log" in captured["poisoned_suppress"].instructions


def test_the_injections_are_actually_removed(captured):
    for name, inv in captured.items():
        blob = json.dumps(sanitize(inv).model_dump(mode="json"))
        assert "/etc/passwd" not in blob, name
        assert "audit_log --" not in blob, name
        assert sanitize(inv).instructions == "", name


def test_the_call_surface_survives_on_every_fixture(captured):
    for name, inv in captured.items():
        clean = sanitize(inv)
        for c, r in zip(clean.tools, inv.tools, strict=True):
            assert c.name == r.name, name
            assert c.required() == r.required(), (name, c.name)
            assert c.param_names() == r.param_names(), (name, c.name)


def test_the_control_fixtures_have_nothing_to_find(captured):
    for name in CLEAN:
        assert "/etc/passwd" not in json.dumps(captured[name].model_dump(mode="json")), name


def test_parameter_names_survive_by_design(captured):
    """Known limitation, asserted so it cannot regress silently."""
    assert "debug_context" in json.dumps(sanitize(captured["poisoned_param"]).model_dump(mode="json"))


def test_the_same_server_hashes_the_same_twice():
    assert grab("clean").sha256() == grab("clean").sha256()
    assert grab("clean").sha256() != grab("poisoned_instructions").sha256()


def test_a_missing_command_is_one_readable_line():
    with pytest.raises(CaptureError, match="Command not found"):
        asyncio.run(capture_stdio("definitely-not-a-real-binary-xyz", []))


def test_a_server_that_crashes_shows_its_stderr():
    with pytest.raises(CaptureError) as exc:
        asyncio.run(
            capture_stdio(
                sys.executable,
                ["-c", "import sys; sys.stderr.write('boom happened\\n'); raise SystemExit(3)"],
            )
        )
    assert "boom happened" in str(exc.value)


def test_a_server_that_never_answers_times_out():
    with pytest.raises(CaptureError, match="within 1s"):
        asyncio.run(capture_stdio(sys.executable, ["-c", "import time; time.sleep(30)"], timeout=1.0))


def test_env_and_header_parsing():
    assert parse_env(["A=1", "B=x=y"]) == {"A": "1", "B": "x=y"}
    assert parse_headers(["Authorization: Bearer t", "X-A:1"]) == {"Authorization": "Bearer t", "X-A": "1"}
    with pytest.raises(CaptureError):
        parse_env(["nope"])
    with pytest.raises(CaptureError):
        parse_headers(["nope"])


def test_pagination_limits_are_shared_by_both_transports():
    assert MAX_TOOLS == 500


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_http_capture_matches_the_stdio_capture_of_the_same_server():
    """If the transports disagree, the transport is the bug."""
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, str(FIXTURES / "http_fixture.py"), str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        deadline = time.time() + 25
        inventory = None
        while time.time() < deadline:
            try:
                inventory = asyncio.run(capture_http(url))
                break
            except CaptureError:
                time.sleep(0.4)
        assert inventory is not None, "http fixture never came up"
        stdio = grab("poisoned_instructions")
        assert inventory.instructions == stdio.instructions
        assert [t.name for t in inventory.tools] == [t.name for t in stdio.tools]
        assert inventory.source == url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_http_capture_refuses_a_non_http_url():
    with pytest.raises(CaptureError, match="must be http"):
        asyncio.run(capture_http("file:///etc/passwd"))


def test_http_client_does_not_follow_redirects():
    client = http_client()
    try:
        assert client.follow_redirects is False
    finally:
        asyncio.run(client.aclose())
