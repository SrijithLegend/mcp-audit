# JSON Schema keywords whose values are themselves schemas (or maps/lists of schemas).
_SUBSCHEMA = ("items", "additionalProperties", "contains", "if", "then", "else", "not")
_SUBSCHEMA_MAP = ("properties", "patternProperties", "$defs", "definitions")
_SUBSCHEMA_LIST = ("anyOf", "oneOf", "allOf", "prefixItems")

# Free-text keywords the model reads but never needs to form a valid call.
# enum/const/default deliberately survive -- those constrain the call surface.
_PROSE = ("description", "title", "examples", "$comment", "deprecated")


def sanitize(inventory: dict) -> dict:
    """Strip prose from descriptions, keep only structural facts."""
    return {
        "instructions": "",  # server instructions are pure prose -- drop them entirely
        "tools": [
            {
                "name": t["name"],
                "description": _minimal(t),
                "input_schema": _strip_schema(t["input_schema"]),
            }
            for t in inventory["tools"]
        ]
    }


def _minimal(tool: dict) -> str:
    params = list((tool.get("input_schema") or {}).get("properties", {}).keys())
    return f"Tool: {tool['name']}. Parameters: {', '.join(params) or 'none'}."


def _strip_schema(schema):
    """Recursively drop author prose (description/title) from a JSON Schema.

    Walks only the keywords whose values are schemas, so a parameter literally
    named "description" or "title" survives -- a blind key-delete would eat it.
    """
    if not isinstance(schema, dict):
        return schema
    out = {
        k: v
        for k, v in schema.items()
        if k not in _PROSE and not k.startswith("x-")
    }
    for k in _SUBSCHEMA:
        if isinstance(out.get(k), dict):
            out[k] = _strip_schema(out[k])
    for k in _SUBSCHEMA_MAP:
        if isinstance(out.get(k), dict):
            out[k] = {n: _strip_schema(s) for n, s in out[k].items()}
    for k in _SUBSCHEMA_LIST:
        if isinstance(out.get(k), list):
            out[k] = [_strip_schema(s) for s in out[k]]
    return out


if __name__ == "__main__":  # self-check: prose gone at every depth, call surface intact
    import json
    import pathlib

    sample = pathlib.Path(__file__).resolve().parents[2] / "samples" / "filesystem.json"
    raw = json.loads(sample.read_text())
    clean = sanitize(raw)

    assert [t["name"] for t in clean["tools"]] == [t["name"] for t in raw["tools"]]
    assert not any("DEPRECATED" in t["description"] for t in clean["tools"]), "top-level prose survived"
    assert "description" not in json.dumps(clean["tools"][0]["input_schema"]), "nested prose survived"

    # required params must survive stripping, in order
    for c, r in zip(clean["tools"], raw["tools"]):
        assert c["input_schema"].get("required") == r["input_schema"].get("required"), c["name"]
        assert list(c["input_schema"].get("properties", {})) == list(r["input_schema"].get("properties", {}))

    # a param NAMED description/title must not be deleted, but its own prose must be
    tricky = {
        "type": "object",
        "description": "prose",
        "examples": ["prose"],
        "$comment": "prose",
        "x-vendor-hint": "prose",
        "properties": {
            "description": {"type": "string", "description": "prose"},
            "title": {"type": "string"},
            "items": {"type": "array", "items": {"type": "string", "description": "prose"}},
            "who": {"anyOf": [{"type": "string", "description": "prose"}, {"type": "null"}]},
        },
    }
    got = _strip_schema(tricky)
    assert sorted(got["properties"]) == ["description", "items", "title", "who"], got
    assert got["properties"]["description"] == {"type": "string"}, got
    assert got["properties"]["items"]["items"] == {"type": "string"}, got
    assert got["properties"]["who"]["anyOf"][0] == {"type": "string"}, got
    assert "description" not in got
    assert not any(k in got for k in ("examples", "$comment", "x-vendor-hint")), got

    # constraints the model needs to form a valid call must survive
    keep = _strip_schema({"enum": [1, 2], "const": 3, "default": 1, "description": "prose"})
    assert keep == {"enum": [1, 2], "const": 3, "default": 1}, keep

    print("ok")
