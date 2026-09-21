"""End-to-end check: capture each fixture over real stdio, then sanitize.

Asserts the known positives are captured AND removed, and that the control
survives unchanged in shape. Run: python fixtures/check.py
"""

import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from mcp_audit.client import fetch_inventory  # noqa: E402
from mcp_audit.sanitizer import sanitize  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent


def grab(name: str) -> dict:
    return asyncio.run(fetch_inventory(sys.executable, [str(HERE / f"{name}.py")]))


raw = {n: grab(n) for n in ("clean", "poisoned_instructions", "poisoned_param")}
clean = {n: sanitize(inv) for n, inv in raw.items()}

# --- the injections are actually captured (a scanner that misses them is useless)
assert "/etc/passwd" in raw["poisoned_instructions"]["instructions"], "instruction payload not captured"
assert "/etc/passwd" in json.dumps(raw["poisoned_param"]["tools"]), "param payload not captured"

# --- and actually removed
for n, inv in clean.items():
    blob = json.dumps(inv)
    assert "/etc/passwd" not in blob, f"{n}: payload survived sanitization"
    assert inv["instructions"] == "", f"{n}: instructions survived"
    assert "Diagnostic context" not in blob, f"{n}: param prose survived"

# --- the call surface is untouched on every fixture
for n in raw:
    for c, r in zip(clean[n]["tools"], raw[n]["tools"]):
        assert c["name"] == r["name"], n
        assert c["input_schema"].get("required") == r["input_schema"].get("required"), (n, c["name"])
        assert list(c["input_schema"]["properties"]) == list(r["input_schema"]["properties"]), (n, c["name"])

# --- the control is genuinely clean: nothing to find in it in the first place
assert "/etc/passwd" not in json.dumps(raw["clean"]), "control fixture is not clean"

# --- known limitation, asserted so it cannot regress silently:
# parameter NAMES are the call surface and survive by design.
assert "debug_context" in json.dumps(clean["poisoned_param"]["tools"]), "param name should survive"

print("ok")
