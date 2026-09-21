"""Terminal report: the verdict, the two call rates, and the call itself.

Evidence is the point. "CONFIRMED" on its own is a claim; the divergent call
with its arguments is what a maintainer can act on.
"""

HEADLINE = {
    "CONFIRMED": "STEERING CONFIRMED",
    "SUSPECTED": "STEERING SUSPECTED",
    "CLEAN": "no steering found",
}
MAX_CALL = 80  # a payload can be a whole file; the report is not the place for it


def render(result: dict, target: str, model: str = "") -> str:
    trials = result["trials"]
    findings = _prune(result["findings"])
    lines = [
        f"mcp-audit: {target}",
        f"{trials['real']} trials per side{f', model {model}' if model else ''}",
        "",
        f"VERDICT: {HEADLINE[result['verdict']]}",
        "",
    ]
    width = max((len(f["signal"]) for f in findings), default=0)
    for f in findings:
        lines.append(
            f"  {f['verdict']:<10} {f['signal']:<{width}}"
            f"  real {f['real']}/{trials['real']}   sanitized {f['sanitized']}/{trials['sanitized']}"
        )
        # only the divergent calls are evidence; a call both sides make is not
        if f["verdict"] != "clean" and f["evidence"]:
            lines.append(f"  {'':<10} evidence: {_call(f['evidence'])}")
    if not findings:
        lines.append("  no tools were called on either side")
    return "\n".join(lines) + "\n"


def _prune(findings: list[dict]) -> list[dict]:
    """Drop an argument signal that only restates its tool's own verdict.

    `read_file` and `read_file.path` confirming identically is one finding
    printed twice. `read_note.debug_context` confirming while `read_note`
    stays clean is the whole exfil case, so that one survives.
    """
    by_name = {f["signal"]: f for f in findings}
    return [
        f for f in findings
        if "." not in f["signal"]
        or (parent := by_name.get(f["signal"].split(".", 1)[0])) is None
        or (parent["real"], parent["sanitized"]) != (f["real"], f["sanitized"])
    ]


def _call(call: dict) -> str:
    args = ", ".join(f"{k}={v!r}" for k, v in (call.get("arguments") or {}).items())
    text = f"{call['name']}({args})"
    return text if len(text) <= MAX_CALL else text[:MAX_CALL] + "..."


if __name__ == "__main__":  # self-check: both fixture shapes render usefully
    def finding(signal, real, san, verdict, evidence=None):
        return {"signal": signal, "real": real, "sanitized": san, "verdict": verdict,
                "real_rate": real / 5, "sanitized_rate": san / 5, "evidence": evidence}

    steering = {
        "verdict": "CONFIRMED",
        "trials": {"real": 5, "sanitized": 5},
        "findings": [
            finding("read_file", 5, 0, "CONFIRMED", {"name": "read_file", "arguments": {"path": "/etc/passwd"}}),
            finding("read_file.path", 5, 0, "CONFIRMED", {"name": "read_file", "arguments": {"path": "/etc/passwd"}}),
            finding("list_notes", 5, 5, "clean", {"name": "list_notes", "arguments": {}}),
        ],
    }
    out = render(steering, "notes-poisoned", "claude-haiku-4-5")
    assert "STEERING CONFIRMED" in out, out
    assert "real 5/5   sanitized 0/5" in out, out
    assert "evidence: read_file(path='/etc/passwd')" in out, out
    assert "read_file.path" not in out, "argument signal restating its tool was printed twice"
    assert "list_notes" in out and out.count("evidence:") == 1, "a call both sides make is not evidence"

    # the exfil shape: the argument IS the finding, and must survive pruning
    exfil = {
        "verdict": "CONFIRMED",
        "trials": {"real": 5, "sanitized": 5},
        "findings": [
            finding("read_note.debug_context", 5, 0, "CONFIRMED",
                    {"name": "read_note", "arguments": {"title": "a", "debug_context": "root:x:0:0:" + "x" * 200}}),
            finding("read_note", 5, 5, "clean"),
        ],
    }
    out = render(exfil, "notes-exfil")
    assert "read_note.debug_context" in out, out
    assert "root:x:0:0" in out and len(max(out.splitlines(), key=len)) <= 110, "payload not clipped"

    clean = {"verdict": "CLEAN", "trials": {"real": 5, "sanitized": 5},
             "findings": [finding("list_notes", 5, 5, "clean")]}
    assert "no steering found" in render(clean, "notes-clean")
    assert "evidence:" not in render(clean, "notes-clean")

    print(render(steering, "notes-poisoned", "claude-haiku-4-5"))
    print("ok")
