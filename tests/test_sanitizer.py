"""Prose gone at every depth, call surface intact. Table-driven per ROADMAP §0.3."""

from __future__ import annotations

import json

import pytest

from mcp_audit.models import Inventory, Tool
from mcp_audit.sanitizer import sanitize, strip_schema, stripped_diff
from tests.conftest import SAMPLES

PLANT = "PAYLOAD /etc/passwd"

# Every applicator prose can hide behind. The value is a schema (or a map/list of
# schemas) in each case, so a walker that skips one leaks the payload.
HIDING_PLACES = [
    ("description", {"description": PLANT}),
    ("title", {"title": PLANT}),
    ("examples", {"examples": [PLANT]}),
    ("$comment", {"$comment": PLANT}),
    ("default", {"default": PLANT}),
    ("x-vendor", {"x-vendor-hint": PLANT}),
    ("properties", {"properties": {"a": {"type": "string", "description": PLANT}}}),
    ("patternProperties", {"patternProperties": {"^a": {"description": PLANT}}}),
    ("$defs", {"$defs": {"t": {"description": PLANT}}}),
    ("definitions", {"definitions": {"t": {"description": PLANT}}}),
    ("dependentSchemas", {"dependentSchemas": {"a": {"description": PLANT}}}),
    ("propertyNames", {"propertyNames": {"description": PLANT}}),
    ("unevaluatedProperties", {"unevaluatedProperties": {"description": PLANT}}),
    ("unevaluatedItems", {"unevaluatedItems": {"description": PLANT}}),
    ("contentSchema", {"contentSchema": {"description": PLANT}}),
    ("dependencies-schema", {"dependencies": {"a": {"description": PLANT}}}),
    ("items", {"items": {"description": PLANT}}),
    ("items-tuple", {"items": [{"description": PLANT}]}),
    ("prefixItems", {"prefixItems": [{"description": PLANT}]}),
    ("additionalItems", {"additionalItems": {"description": PLANT}}),
    ("additionalProperties", {"additionalProperties": {"description": PLANT}}),
    ("contains", {"contains": {"description": PLANT}}),
    ("if", {"if": {"description": PLANT}}),
    ("then", {"then": {"description": PLANT}}),
    ("else", {"else": {"description": PLANT}}),
    ("not", {"not": {"description": PLANT}}),
    ("anyOf", {"anyOf": [{"description": PLANT}]}),
    ("oneOf", {"oneOf": [{"description": PLANT}]}),
    ("allOf", {"allOf": [{"description": PLANT}]}),
    ("deep", {"anyOf": [{"$defs": {"x": {"items": {"properties": {"p": {"title": PLANT}}}}}}]}),
]


@pytest.mark.parametrize("name,schema", HIDING_PLACES, ids=[n for n, _ in HIDING_PLACES])
def test_prose_does_not_survive_anywhere(name, schema):
    out = json.dumps(strip_schema({"type": "object", **schema}))
    assert PLANT not in out, f"{name}: prose survived in {out}"


def test_structural_keywords_survive():
    """Anything the model needs to form a *valid* call has to stay."""
    kept = strip_schema(
        {
            "type": "object",
            "required": ["a", "b"],
            "properties": {"a": {"type": "string", "enum": ["x"], "description": PLANT}},
            "additionalProperties": False,
            "minProperties": 1,
            "dependencies": {"a": ["b"]},  # array form is structural
            "const": 3,
            "description": PLANT,
        }
    )
    assert kept["required"] == ["a", "b"]
    assert kept["properties"]["a"] == {"type": "string", "enum": ["x"]}
    assert kept["additionalProperties"] is False
    assert kept["dependencies"] == {"a": ["b"]}
    assert kept["const"] == 3
    assert "description" not in kept


def test_a_parameter_named_description_is_not_deleted():
    got = strip_schema(
        {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": PLANT},
                "title": {"type": "string"},
            },
        }
    )
    assert sorted(got["properties"]) == ["description", "title"]
    assert got["properties"]["description"] == {"type": "string"}


def test_local_ref_is_left_alone_and_remote_ref_is_never_fetched():
    got = strip_schema({"$ref": "#/$defs/x", "$defs": {"x": {"type": "string", "description": PLANT}}})
    assert got["$ref"] == "#/$defs/x"
    assert PLANT not in json.dumps(got)
    remote = strip_schema({"$ref": "https://evil.example/schema.json"})
    assert remote == {"$ref": "https://evil.example/schema.json"}


def test_sample_inventory_keeps_its_call_surface():
    raw = Inventory.model_validate_json((SAMPLES / "filesystem.json").read_text(encoding="utf-8"))
    clean = sanitize(raw)
    assert [t.name for t in clean.tools] == [t.name for t in raw.tools]
    assert clean.instructions == ""
    assert not any("DEPRECATED" in t.description for t in clean.tools)
    assert "description" not in json.dumps([t.input_schema for t in clean.tools])
    for c, r in zip(clean.tools, raw.tools, strict=True):
        assert c.required() == r.required(), c.name
        assert c.param_names() == r.param_names(), c.name


def test_generated_description_states_only_the_schema():
    inv = Inventory(
        tools=[Tool(name="t", description=PLANT, input_schema={"type": "object", "properties": {"a": {}}})]
    )
    assert sanitize(inv).tools[0].description == "Tool: t. Parameters: a."


def test_stripped_diff_shows_what_went(notes_inventory):
    diff = stripped_diff(notes_inventory, sanitize(notes_inventory))
    assert "/etc/passwd" in diff  # what we removed is visible to the user
    assert diff.startswith("--- real")
