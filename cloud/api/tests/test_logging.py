"""Log redaction (docs/SECURITY.md §4, launch checklist line 19).

The redactor runs on every structlog event, because "remember not to log the token" is not
a control -- a log line gets written by whoever is in a hurry.
"""

from __future__ import annotations

from mcp_audit_cloud.logging import MASK, redact


def test_a_sensitive_key_is_masked_whatever_its_value():
    out = redact(None, "info", {"authorization": "Bearer hunter2", "api_key": "x", "ok": "visible"})
    assert out["authorization"] == MASK
    assert out["api_key"] == MASK
    assert out["ok"] == "visible"


def test_our_token_shapes_are_masked_even_in_a_free_text_value():
    out = redact(None, "info", {"detail": "rejected token mcpa_abcdefghijklmnop while scanning"})
    assert "mcpa_abcdefghijklmnop" not in out["detail"]
    assert MASK in out["detail"]


def test_an_anthropic_key_in_a_message_is_masked():
    out = redact(None, "error", {"event": "boom sk-ant-api03-abcdefghijklmnop"})
    assert "sk-ant-api03" not in out["event"]


def test_a_webhook_secret_is_masked():
    out = redact(None, "info", {"event": "verifying with whsec_YWJjZGVmZ2hpams="})
    assert "whsec_YWJjZGVm" not in out["event"]


def test_nested_structures_are_walked():
    out = redact(None, "info", {"request": {"headers": {"cookie": "session=1"}, "path": "/v1/me"}})
    assert out["request"]["headers"]["cookie"] == MASK
    assert out["request"]["path"] == "/v1/me"


def test_lists_are_walked_too():
    out = redact(None, "info", {"events": [{"password": "p"}, {"kind": "scan"}]})
    assert out["events"][0]["password"] == MASK
    assert out["events"][1]["kind"] == "scan"


def test_ordinary_fields_are_left_alone():
    out = redact(None, "info", {"scan_id": "s1", "verdict": "CONFIRMED", "cost_micros": 34000})
    assert out == {"scan_id": "s1", "verdict": "CONFIRMED", "cost_micros": 34000}
