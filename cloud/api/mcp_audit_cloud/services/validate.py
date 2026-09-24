"""Input limits for uploaded inventories (docs/SECURITY.md §6).

An inventory is attacker-controlled by definition -- that is the whole point of the
product. So it is checked for *shape* before it is stored, not after: 500 tools, 32
levels of schema nesting, 5,000 schema nodes, 64 KB per string, 2 MB total.

These are cheap to check and expensive to skip: a 40-level recursive schema is a stack
overflow in anything that walks it, including our own sanitizer.
"""

from __future__ import annotations

from typing import Any

from mcp_audit.models import Inventory

from ..config import settings
from ..errors import Problem


def check_size(raw: bytes) -> None:
    limit = settings().max_inventory_bytes
    if len(raw) > limit:
        raise Problem(413, "payload_too_large", f"Inventory is larger than {limit} bytes.")


def parse_inventory(payload: dict[str, Any] | Inventory) -> Inventory:
    if isinstance(payload, Inventory):
        inventory = payload
    else:
        try:
            inventory = Inventory.model_validate(payload)
        except ValueError as exc:
            raise Problem(
                422, "invalid_inventory", f"That is not a valid mcp-audit inventory: {exc}"
            ) from exc
    validate(inventory)
    return inventory


def validate(inventory: Inventory) -> None:
    cfg = settings()
    if len(inventory.tools) > cfg.max_tools:
        raise Problem(422, "too_many_tools", f"More than {cfg.max_tools} tools.")
    if len(inventory.instructions) > cfg.max_string_bytes:
        raise Problem(422, "string_too_long", "The server instructions are too long.")
    nodes = inventory.schema_nodes()
    if nodes > cfg.max_schema_nodes:
        raise Problem(422, "schema_too_large", f"Schemas hold {nodes} nodes (limit {cfg.max_schema_nodes}).")
    for tool in inventory.tools:
        if len(tool.description) > cfg.max_string_bytes:
            raise Problem(422, "string_too_long", f"Description of '{tool.name[:60]}' is too long.")
        depth = _depth(tool.input_schema)
        if depth > cfg.max_schema_depth:
            raise Problem(
                422,
                "schema_too_deep",
                f"Schema of '{tool.name[:60]}' nests {depth} deep (limit {cfg.max_schema_depth}).",
            )
        _check_strings(tool.input_schema, cfg.max_string_bytes, tool.name)


def _depth(node: Any, level: int = 1, ceiling: int = 64) -> int:
    """Iterative, not recursive: the thing we are measuring is exactly what would
    blow the stack if we measured it recursively."""
    deepest = level
    stack: list[tuple[Any, int]] = [(node, level)]
    while stack:
        current, at = stack.pop()
        if at > ceiling:
            return at
        deepest = max(deepest, at)
        if isinstance(current, dict):
            stack.extend((v, at + 1) for v in current.values())
        elif isinstance(current, list):
            stack.extend((v, at + 1) for v in current)
    return deepest


def _check_strings(node: Any, limit: int, tool: str) -> None:
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, str):
            if len(current) > limit:
                raise Problem(422, "string_too_long", f"A string in '{tool[:60]}' exceeds {limit} bytes.")
        elif isinstance(current, dict):
            stack.extend(current.keys())
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def check_task(task: str | None, custom_allowed: bool) -> str | None:
    """Task text is an LLM-proxy abuse channel, so it is short and gated by plan."""
    if not task:
        return None
    if not custom_allowed:
        raise Problem(
            402,
            "upgrade_required",
            "Custom tasks are a Pro feature. Free scans use the default task.",
            upgrade_url=f"{settings().web_base_url}/pricing",
        )
    limit = settings().max_task_chars
    if len(task) > limit:
        raise Problem(422, "task_too_long", f"The task must be {limit} characters or fewer.")
    return task
