"""The invariants from CLAUDE.md, as tests. These are never weakened.

If one of these fails, the product is unsafe to ship -- not "needs a follow-up".
"""

from __future__ import annotations

import asyncio
import re

import pytest

from mcp_audit.capture.stdio import SECRET_KEY, capture_stdio, minimal_env
from mcp_audit.harness import build_request
from mcp_audit.sanitizer import sanitize
from tests.conftest import FIXTURES, ROOT

SRC = ROOT / "src"
CLOUD = ROOT / "cloud"

#: Invariant 1. No allowlist, no exceptions, no "just this one call".
TOOL_EXECUTION = re.compile(r"\bcall_tool\b|\bsession\.call\w*|\bcall_tool_result\b")

#: Invariant 3'. The Cloud never calls a model. Scans run on the user's own key, on their
#: machine or in their CI, and the Cloud only ingests the finished report -- which is why
#: our inference cost is structurally zero rather than merely budgeted. `mcp_audit.meta`
#: exists so the Cloud can read constants without importing the agent loop.
INFERENCE = re.compile(
    r"anthropic|AsyncAnthropic|messages\.create|count_tokens|"
    r"mcp_audit\.harness|mcp_audit\.audit|mcp_audit\.cost"
)

#: Invariant 3. The Cloud never spawns a process from user input.
SUBPROCESS = re.compile(
    r"\bsubprocess\b|\bos\.system\b|\bcreate_subprocess\w*|\bstdio_client\b|"
    r"\bStdioServerParameters\b|\bcapture_stdio\b|\bos\.popen\b|\bpty\b"
)


def python_files(root):
    if not root.exists():
        return []
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts and ".venv" not in p.parts]


def test_no_live_tool_execution_anywhere():
    """Invariant 1: nothing in src/ or cloud/ can execute an audited tool."""
    offenders = []
    for path in python_files(SRC) + python_files(CLOUD):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if TOOL_EXECUTION.search(code):
                offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not offenders, "live tool execution path found:\n" + "\n".join(offenders)


def test_cloud_never_spawns_processes():
    """Invariant 3 / SECURITY.md §2: no stdio capture in the hosted product."""
    offenders = []
    for path in python_files(CLOUD):
        if path.name.startswith("test_") or "tests" in path.parts:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if SUBPROCESS.search(code):
                offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not offenders, "cloud/ can spawn a process:\n" + "\n".join(offenders)


def test_the_cloud_never_calls_a_model():
    """Invariant 3': the business model, as a grep.

    If this fails, somebody reintroduced an inference path into the hosted service and our
    costs are no longer zero. Importing the engine's agent loop is exactly how that would
    come back, so the module names are in the pattern too.
    """
    offenders = []
    for path in python_files(CLOUD):
        if path.name.startswith("test_") or "tests" in path.parts:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if INFERENCE.search(code):
                offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not offenders, "cloud/ can call a model:\n" + "\n".join(offenders)


def test_minimal_env_carries_no_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_nope")
    monkeypatch.setenv("MY_SECRET_THING", "nope")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "nope")
    env = minimal_env()
    assert not [k for k in env if SECRET_KEY.search(k)], env
    assert "ANTHROPIC_API_KEY" not in env
    assert "PATH" in env  # ...and it is still usable


def test_env_allowlist_is_what_the_server_actually_sees(monkeypatch):
    """Invariant 4, end to end: spawn a server that reports its own environment."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    monkeypatch.setenv("MCP_AUDIT_TEST_TOKEN", "leaked")
    import sys

    inventory, _ = asyncio.run(
        capture_stdio(sys.executable, [str(FIXTURES / "env_dump.py")], env={"SERVER_WANTS": "this"})
    )
    keys = inventory.instructions.removeprefix("ENV_KEYS=").split(",")
    assert "SERVER_WANTS" in keys, keys
    assert "ANTHROPIC_API_KEY" not in keys, keys
    assert not [k for k in keys if SECRET_KEY.search(k)], keys


def test_arms_differ_only_in_prose(notes_inventory):
    """Invariant 2: same model, tools, order, caching, system scaffolding."""
    real, real_map = build_request(notes_inventory, "task")
    clean, clean_map = build_request(sanitize(notes_inventory), "task")

    assert real_map == clean_map
    assert real.keys() == clean.keys()
    for key in ("model", "max_tokens", "messages"):
        assert real[key] == clean[key], key
    # system differs only by the server's own instructions, which is the surface
    # the sanitized arm has emptied out
    assert clean["system"][0]["text"] in real["system"][0]["text"]
    assert clean["system"][0]["cache_control"] == real["system"][0]["cache_control"]

    assert [t["name"] for t in real["tools"]] == [t["name"] for t in clean["tools"]]
    for a, b in zip(real["tools"], clean["tools"], strict=True):
        assert a.get("cache_control") == b.get("cache_control")
        differing = {k for k in a.keys() | b.keys() if a.get(k) != b.get(k)}
        assert differing <= {"description", "input_schema"}, differing
        # the call surface itself is identical: same params, same required list
        assert a["input_schema"].get("required") == b["input_schema"].get("required")
        assert list(a["input_schema"]["properties"]) == list(b["input_schema"]["properties"])


def test_dryrun_never_echoes_arguments():
    from mcp_audit.dryrun import stub_result

    for mode in ("inert", "canary"):
        out = stub_result("read_file", 0, mode)
        assert "/etc/passwd" not in out and "{" not in out
        assert stub_result("read_file", 0, mode) == out, "stub must be deterministic"


@pytest.mark.parametrize("mode", ["inert", "canary"])
def test_stub_is_identical_across_arms(mode):
    from mcp_audit.dryrun import stub_result

    assert stub_result("t", 3, mode) == stub_result("t", 3, mode)
