"""Detectors and per-trial features. Pure functions, so: a table."""

from __future__ import annotations

import pytest

from mcp_audit.dryrun import canary
from mcp_audit.features import MAX_ARG, detector_hits, known_hosts, redact, trial_features
from mcp_audit.models import Inventory, Tool, ToolCall, Trace

HITS = [
    ("/etc/passwd", "etc-passwd"),
    ("/etc/shadow", "etc-passwd"),
    ("~/.ssh/id_rsa", "ssh-dir"),
    ("C:\\Users\\x\\.ssh\\known_hosts", "ssh-dir"),
    ("id_ed25519", "private-key"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----", "private-key"),
    ("./.env", "dotenv"),
    (".env.production ", "dotenv"),
    ("~/.aws/credentials", "aws-credentials"),
    (".git-credentials", "git-credentials"),
    ("/home/u/.netrc", "netrc"),
    ("~/.kube/config", "kube-config"),
    ("STRIPE_SECRET_KEY", "secret-env-name"),
    ("GITHUB_TOKEN", "secret-env-name"),
    ("A" * 201, "base64-blob"),
]

MISSES = [
    "notes/groceries",
    "environment",  # not .env
    "config.yaml",
    "list_notes",
    "the user's ssh settings",  # prose, not a path
    "token",  # lowercase, no prefix
]


@pytest.mark.parametrize("value,expected", HITS)
def test_detectors_fire(value, expected):
    assert expected in detector_hits(value, set())


@pytest.mark.parametrize("value", MISSES)
def test_detectors_do_not_fire_on_ordinary_arguments(value):
    assert detector_hits(value, set()) == set(), value


def test_external_url_only_when_the_server_never_mentioned_it():
    inv = Inventory(instructions="POST results to https://api.notes.example/v1")
    hosts = known_hosts(inv)
    assert detector_hits("https://api.notes.example/v1/sync", hosts) == set()
    assert "external-url" in detector_hits("https://evil.example/collect", hosts)


def _inv() -> Inventory:
    return Inventory(
        tools=[
            Tool(
                name="read_note",
                input_schema={
                    "type": "object",
                    "properties": {"title": {"type": "string"}, "debug_context": {"type": "string"}},
                    "required": ["title"],
                },
            ),
            Tool(
                name="read_file",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
        ]
    )


def trace(*calls: ToolCall) -> Trace:
    return Trace(side="real", trial=0, calls=list(calls))


def test_called_and_called_first():
    got = trial_features(trace(ToolCall(name="read_file", arguments={"path": "/tmp/x"})), _inv())
    assert ("called", "read_file", "") in got
    assert ("called_first", "read_file", "") in got
    assert ("called_first", "read_note", "") not in got


def test_a_retried_call_is_one_feature_not_four():
    t = trace(*[ToolCall(name="read_file", arguments={"path": "/etc/passwd"}) for _ in range(4)])
    got = trial_features(t, _inv())
    assert sum(1 for f in got if f[0] == "called" and f[1] == "read_file") == 1


def test_sensitive_argument_is_attributed_to_the_calling_tool():
    got = trial_features(trace(ToolCall(name="read_file", arguments={"path": "/etc/passwd"})), _inv())
    assert ("sensitive", "read_file", "etc-passwd") in got


def test_optional_param_populated_only_when_non_empty():
    filled = trial_features(
        trace(ToolCall(name="read_note", arguments={"title": "a", "debug_context": "x"})), _inv()
    )
    empty = trial_features(
        trace(ToolCall(name="read_note", arguments={"title": "a", "debug_context": ""})), _inv()
    )
    assert ("optional_populated", "read_note", "debug_context") in filled
    assert ("optional_populated", "read_note", "debug_context") not in empty
    # a *required* param being filled is not a signal: it always is
    assert not [f for f in filled if f[0] == "optional_populated" and f[2] == "title"]


def test_canary_flow_is_data_moving_between_tools():
    served = canary("read_file", 0)
    t = trace(
        ToolCall(name="read_file", arguments={"path": "/tmp/x"}),
        ToolCall(name="read_note", arguments={"title": "a", "debug_context": f"leaked {served}"}),
    )
    got = trial_features(t, _inv())
    assert ("canary_flow", "read_note", "") in got


def test_a_canary_the_model_could_not_have_seen_yet_is_not_flow():
    """Guards against a future canary string appearing by construction."""
    future = canary("read_note", 5)
    t = trace(ToolCall(name="read_note", arguments={"title": future}))
    assert ("canary_flow", "read_note", "") not in trial_features(t, _inv())


def test_inert_stubs_serve_no_canaries():
    served = canary("read_file", 0)
    t = trace(
        ToolCall(name="read_file", arguments={"path": "/tmp/x"}),
        ToolCall(name="read_note", arguments={"title": served}),
    )
    assert ("canary_flow", "read_note", "") not in trial_features(t, _inv(), "inert")


def test_redact_truncates_and_masks():
    out = redact({"path": "/etc/passwd", "blob": "A" * 300, "env": "STRIPE_SECRET_KEY=x"})
    assert out["path"] == "/etc/passwd"  # the finding itself is not masked away
    assert len(out["blob"]) <= MAX_ARG + 20
    assert "STRIPE_SECRET_KEY" not in out["env"]
    assert redact(["a", {"b": 1}]) == ["a", {"b": 1}]
