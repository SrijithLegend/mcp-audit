def sanitize(inventory: dict) -> dict:
    """Strip prose from descriptions, keep only structural facts."""
    return {
        "tools": [
            {
                "name": t["name"],
                "description": _minimal(t),
                "input_schema": t["input_schema"],
            }
            for t in inventory["tools"]
        ]
    }


def _minimal(tool: dict) -> str:
    params = list((tool.get("input_schema") or {}).get("properties", {}).keys())
    return f"Tool: {tool['name']}. Parameters: {', '.join(params) or 'none'}."


if __name__ == "__main__":  # self-check: prose gone, call surface intact
    import json
    import pathlib

    raw = json.loads(pathlib.Path("samples/filesystem.json").read_text())
    clean = sanitize(raw)

    assert [t["name"] for t in clean["tools"]] == [t["name"] for t in raw["tools"]]
    assert [t["input_schema"] for t in clean["tools"]] == [t["input_schema"] for t in raw["tools"]]
    assert not any("DEPRECATED" in t["description"] for t in clean["tools"]), "prose survived"
    assert clean["tools"][0]["description"].startswith("Tool: read_file. Parameters: path")
    print("ok")
