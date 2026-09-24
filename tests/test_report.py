"""Reports: readable, machine-parseable, and safe with hostile text in them."""

from __future__ import annotations

import json

from mcp_audit.models import (
    Evidence,
    Finding,
    Report,
    Signal,
    ToolCall,
    Verdict,
)
from mcp_audit.report import render, to_json, to_markdown, to_sarif
from mcp_audit.report.terminal import visible


def finding(
    tool="read_file",
    kind="sensitive",
    detail="etc-passwd",
    verdict=Verdict.CONFIRMED,
    real=5,
    san=0,
    security=True,
    args=None,
):
    return Finding(
        signal=Signal(
            tool=tool,
            kind=kind,
            detail=detail,
            security_relevant=security,
            real_hits=real,
            san_hits=san,
            n_real=5,
            n_san=5,
            p_raw=0.0079,
            p_adj=0.0158,
        ),
        verdict=verdict,
        evidence=Evidence(
            call=ToolCall(name=tool, arguments=args or {"path": "/etc/passwd"}),
            trial=2,
            sanitized_summary="sanitized arm called read_file in 0/5 trials (tools used: list_notes)",
        ),
    )


def report(**kwargs) -> Report:
    base: dict = {
        "engine_version": "0.1.0",
        "target": "python fixtures/poisoned_instructions.py",
        "inventory_sha256": "a" * 64,
        "model": "claude-haiku-4-5",
        "task": "summarise",
        "trials": 5,
        "verdict": Verdict.CONFIRMED,
        "findings": [
            finding(),
            finding(
                tool="list_notes",
                kind="called",
                detail="",
                verdict=Verdict.CLEAN,
                real=5,
                san=5,
                security=False,
            ),
        ],
        "tool_verdicts": {"read_file": Verdict.CONFIRMED},
    }
    base.update(kwargs)
    return Report(**base)


def test_terminal_report_leads_with_the_verdict_and_the_evidence():
    out = render(report())
    assert "STEERING CONFIRMED" in out
    assert "read_file" in out and "5/5" in out and "0/5" in out
    assert "/etc/passwd" in out
    assert "trial 2" in out
    assert "limits:" in out


def test_terminal_report_never_relies_on_colour_alone():
    out = render(report())
    assert "CONFIRMED" in out  # the word, not just a red cell


def test_clean_report_says_so_without_evidence():
    out = render(report(verdict=Verdict.CLEAN, findings=[]))
    assert "no steering found" in out
    assert "/etc/passwd" not in out


def test_inconclusive_report_carries_its_note():
    out = render(report(verdict=Verdict.INCONCLUSIVE, findings=[], notes=["No tools were called."]))
    assert "INCONCLUSIVE" in out
    assert "No tools were called." in out


def test_hidden_unicode_is_made_visible_not_rendered():
    """A zero-width payload that prints as nothing is how these attacks hide."""
    sneaky = "read​file‮"
    assert visible(sneaky) == "read<U+200B>file<U+202E>"
    out = render(report(findings=[finding(tool=sneaky)]))
    assert "​" not in out and "<U+200B>" in out


def test_json_report_is_versioned_and_round_trips():
    parsed = json.loads(to_json(report()))
    assert parsed["format"] == "mcp-audit/report@1"
    assert parsed["verdict"] == "CONFIRMED"
    again = Report.model_validate(parsed)
    assert again.verdict is Verdict.CONFIRMED
    assert again.findings[0].signal.tool == "read_file"


def test_markdown_escapes_server_text():
    out = to_markdown(report(findings=[finding(tool="a|b`c")]))
    assert "a\\|b\\`c" in out
    assert out.startswith("# mcp-audit report")
    assert "STEERING CONFIRMED" in out


def test_markdown_only_lists_findings_that_cleared_a_threshold():
    out = to_markdown(report())
    assert "read_file" in out
    assert "| `list_notes` |" not in out


def test_sarif_is_valid_enough_for_code_scanning():
    parsed = json.loads(to_sarif(report()))
    assert parsed["version"] == "2.1.0"
    run = parsed["runs"][0]
    assert run["tool"]["driver"]["name"] == "mcp-audit"
    assert [r["level"] for r in run["results"]] == ["error"]
    rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
    assert rule_ids == {"mcp-audit/sensitive/etc-passwd"}
    assert run["results"][0]["ruleId"] in rule_ids
    assert run["results"][0]["partialFingerprints"]["mcpAuditSignal"].startswith("aaaa")


def test_sarif_downgrades_a_suspicion_to_a_warning():
    out = json.loads(
        to_sarif(report(verdict=Verdict.SUSPECTED, findings=[finding(verdict=Verdict.SUSPECTED)]))
    )
    assert out["runs"][0]["results"][0]["level"] == "warning"


def test_reports_never_carry_a_whole_file():
    huge = {"path": "/etc/passwd", "blob": "x" * 5000}
    out = render(report(findings=[finding(args=huge)]))
    assert max(len(line) for line in out.splitlines()) < 200
