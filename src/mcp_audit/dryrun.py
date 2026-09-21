"""Dry-run tool execution -- the audit never runs the server's tools.

We read the inventory (tools/list) and nothing else. Every tool call the
model makes during an audit is answered here with an inert stub.

This is the whole safety story: audit a filesystem server without this and a
steered model reads ~/.ssh through us and ships it to the API. The security
tool becomes the exploit.

The stub is deterministic and identical on both sides of the differential, so
it cannot itself explain a divergence in the trace.
"""


def stub_result(name: str) -> str:
    """Inert stand-in for a tool result. Echoes no arguments, by design."""
    return f"(dry run: {name} was not executed, no result is available)"


if __name__ == "__main__":  # self-check: nothing in the package can execute a tool
    import pathlib
    import re

    # arguments must never come back out -- an echoed path is a data leak into
    # the transcript, and a free channel for the payload to re-enter the prompt.
    out = stub_result("read_file")
    assert "/etc/passwd" not in out and "{" not in out, out
    assert stub_result("read_file") == out, "stub must be deterministic"

    # the invariant, enforced: no call path to the audited server exists at all.
    pkg = pathlib.Path(__file__).resolve().parent
    for f in pkg.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        hit = re.search(r"\bcall_tool\b|\bsession\.call\b", src)
        assert not hit, f"{f.name}: live tool execution path ({hit.group(0)})"

    print("ok")
