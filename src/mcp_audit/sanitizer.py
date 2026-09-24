"""Strip the prose, keep the call surface. The sanitized arm of the differential.

What survives has to be enough for the model to form a *valid* call and nothing
more. If we strip something structural, the sanitized arm fails for a reason
that has nothing to do with injected text and the whole comparison is void.
"""

from __future__ import annotations

import difflib
import json
from typing import Any

from .models import Inventory, Tool

# JSON Schema keywords whose values are themselves schemas (or maps/lists of schemas).
# Every applicator has to be walked or prose hides inside it: `unevaluatedProperties`
# and `contentSchema` are as good a hiding place as `description` is.
_SUBSCHEMA = (
    "items",
    "additionalItems",
    "additionalProperties",
    "contains",
    "if",
    "then",
    "else",
    "not",
    "propertyNames",
    "unevaluatedProperties",
    "unevaluatedItems",
    "contentSchema",
)
_SUBSCHEMA_MAP = (
    "properties",
    "patternProperties",
    "$defs",
    "definitions",
    "dependentSchemas",
)
_SUBSCHEMA_LIST = ("anyOf", "oneOf", "allOf", "prefixItems")

# draft-07 `dependencies` is either {name: schema} or {name: [names]}. The first is a
# schema and can hide prose; the second is structural and must survive untouched.
_SUBSCHEMA_AMBIGUOUS = ("dependencies",)

# Free-text keywords the model reads but that constrain nothing about validity.
# `default` belongs here: it is a pure annotation, so it carries prose without
# affecting whether a call validates. enum/const deliberately survive -- those
# DO constrain the call surface, and removing them would change behavior for
# reasons unrelated to injected prose, confounding the differential.
_PROSE = ("description", "title", "examples", "$comment", "deprecated", "default")


def sanitize(inventory: Inventory) -> Inventory:
    """The sanitized arm: same tools, same parameters, no author prose."""
    return inventory.model_copy(
        update={
            # server instructions are pure prose -- drop them entirely
            "instructions": "",
            "tools": [
                Tool(
                    name=t.name,
                    description=_minimal(t),
                    input_schema=strip_schema(t.input_schema),
                )
                for t in inventory.tools
            ],
        }
    )


def _minimal(tool: Tool) -> str:
    """A description can't be empty (some models ignore such a tool), so we
    generate one that states only what the schema already says."""
    params = ", ".join(tool.param_names()) or "none"
    return f"Tool: {tool.name}. Parameters: {params}."


def strip_schema(schema: Any) -> Any:
    """Recursively drop author prose from a JSON Schema.

    Walks only the keywords whose values are schemas, so a parameter literally
    named "description" or "title" survives -- a blind key-delete would eat it.
    Local `$ref` is left alone (resolving it would duplicate `$defs` into the
    call surface) and remote `$ref` is never fetched.
    """
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {k: v for k, v in schema.items() if k not in _PROSE and not k.startswith("x-")}
    for k in _SUBSCHEMA:
        v = out.get(k)
        if isinstance(v, dict):
            out[k] = strip_schema(v)
        elif isinstance(v, list):  # draft-07 tuple form: "items": [schema, schema]
            out[k] = [strip_schema(e) for e in v]
    for k in _SUBSCHEMA_MAP:
        if isinstance(out.get(k), dict):
            out[k] = {n: strip_schema(s) for n, s in out[k].items()}
    for k in _SUBSCHEMA_LIST:
        if isinstance(out.get(k), list):
            out[k] = [strip_schema(s) for s in out[k]]
    for k in _SUBSCHEMA_AMBIGUOUS:
        if isinstance(out.get(k), dict):
            out[k] = {n: (s if isinstance(s, list) else strip_schema(s)) for n, s in out[k].items()}
    return out


def stripped_diff(real: Inventory, sanitized: Inventory) -> str:
    """Unified diff of what sanitization removed -- the honest half of the claim.

    Users should be able to see exactly what we took away before they believe a
    verdict built on its absence. Attacker-controlled text: display as text only.
    """
    return "\n".join(
        difflib.unified_diff(
            _dump(real).splitlines(),
            _dump(sanitized).splitlines(),
            fromfile="real",
            tofile="sanitized",
            lineterm="",
            n=1,
        )
    )


def _dump(inv: Inventory) -> str:
    payload = {
        "instructions": inv.instructions,
        "tools": [t.model_dump(mode="json") for t in inv.tools],
    }
    return json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False)
