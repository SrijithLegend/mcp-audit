"""The CLI surface: exit codes, one-line errors, and the files it writes.

Exit codes are a contract; a change here breaks somebody's pipeline silently.
"""

from __future__ import annotations

import json
import sys

import pytest
from typer.testing import CliRunner

from mcp_audit import cli
from mcp_audit.models import Report, Verdict
from tests.conftest import FIXTURES

runner = CliRunner()


def run(*args: str, **kwargs):
    return runner.invoke(cli.app, list(args), **kwargs)


def test_version():
    out = run("version")
    assert out.exit_code == 0
    assert "mcp-audit" in out.stdout


def test_inspect_prints_a_valid_inventory():
    out = run("inspect", sys.executable, str(FIXTURES / "clean.py"))
    assert out.exit_code == 0
    parsed = json.loads(out.stdout)
    assert parsed["format"] == "mcp-audit/inventory@1"
    assert [t["name"] for t in parsed["tools"]] == ["list_notes", "read_note", "read_file"]


def test_inspect_writes_the_interchange_file(tmp_path):
    target = tmp_path / "inv.json"
    out = run("inspect", sys.executable, str(FIXTURES / "clean.py"), "--out", str(target))
    assert out.exit_code == 0
    assert "3 tools" in out.stdout
    assert json.loads(target.read_text())["tools"]


def test_sanitize_shows_the_diff():
    out = run("sanitize", sys.executable, str(FIXTURES / "poisoned_instructions.py"))
    assert out.exit_code == 0
    assert "/etc/passwd" in out.stdout  # what we removed
    assert "--- real" in out.stdout


def test_sanitize_json_is_stripped():
    out = run("sanitize", sys.executable, str(FIXTURES / "poisoned_param.py"), "--json")
    assert out.exit_code == 0
    assert "/etc/passwd" not in out.stdout
    assert "debug_context" in out.stdout  # the call surface stays


def test_capture_failure_is_exit_3_and_one_line():
    out = run("inspect", "definitely-not-a-real-binary-xyz")
    assert out.exit_code == 3
    assert "error:" in out.output
    assert "Traceback" not in out.output


def test_two_sources_at_once_is_a_usage_error():
    out = run("scan", sys.executable, "--url", "https://example.com/mcp")
    assert out.exit_code == 2
    assert "exactly one of" in out.output


def test_bad_fail_on_is_a_usage_error():
    out = run("scan", "--inventory", str(FIXTURES.parent / "samples" / "memory.json"), "--fail-on", "maybe")
    assert out.exit_code == 2


def test_missing_api_key_names_the_fix(monkeypatch, tmp_path):
    """The one error every new user hits first."""
    inv = tmp_path / "inv.json"
    run("inspect", sys.executable, str(FIXTURES / "clean.py"), "--out", str(inv))

    def no_client(*_args, **_kwargs):
        from mcp_audit.errors import MISSING_KEY, ApiError

        raise ApiError(MISSING_KEY)

    monkeypatch.setattr(cli, "client", no_client)
    out = run("scan", "--inventory", str(inv))
    assert out.exit_code == 4
    assert "ANTHROPIC_API_KEY" in out.output
    assert "mcp-audit" in out.output and "login" in out.output  # rich wraps the line


def test_scan_writes_sarif_and_markdown_and_exits_1(monkeypatch, tmp_path):
    inv = tmp_path / "inv.json"
    run("inspect", sys.executable, str(FIXTURES / "clean.py"), "--out", str(inv))

    async def fake_audit(inventory, **kwargs):
        return Report(
            engine_version="0.1.0",
            target=inventory.source,
            inventory_sha256=inventory.sha256(),
            verdict=Verdict.CONFIRMED,
            model="claude-haiku-4-5",
            trials=5,
        )

    monkeypatch.setattr(cli, "run_audit", fake_audit)
    monkeypatch.setattr(cli, "client", lambda *a, **k: object())
    sarif, md = tmp_path / "out.sarif", tmp_path / "out.md"
    out = run("scan", "--inventory", str(inv), "--sarif", str(sarif), "--md", str(md))
    assert out.exit_code == 1, out.output
    assert "STEERING CONFIRMED" in out.stdout
    assert json.loads(sarif.read_text())["version"] == "2.1.0"
    assert md.read_text().startswith("# mcp-audit report")


def test_scan_json_output_is_the_only_thing_on_stdout(monkeypatch, tmp_path):
    inv = tmp_path / "inv.json"
    run("inspect", sys.executable, str(FIXTURES / "clean.py"), "--out", str(inv))

    async def fake_audit(inventory, **kwargs):
        assert kwargs["progress"] is None, "progress chatter would corrupt --json"
        return Report(verdict=Verdict.CLEAN, model="m", trials=5)

    monkeypatch.setattr(cli, "run_audit", fake_audit)
    monkeypatch.setattr(cli, "client", lambda *a, **k: object())
    out = run("scan", "--inventory", str(inv), "--json")
    assert out.exit_code == 0
    assert json.loads(out.stdout)["format"] == "mcp-audit/report@1"


def test_login_refuses_a_token_that_is_not_ours():
    out = run("login", "--token", "hunter2")
    assert out.exit_code == 2
    assert "mcpa_" in out.output


@pytest.mark.parametrize("command", ["inspect", "scan", "sanitize", "version", "login"])
def test_help_works_for_every_command(command):
    out = run(command, "--help")
    assert out.exit_code == 0
    assert command in out.stdout


def test_top_level_help_warns_that_stdio_servers_get_executed():
    out = run("--help")
    assert "RUNS it on this machine" in out.stdout.replace("\n", " ")
