"""`tools/list` is paginated. Follow the cursor, but not forever.

A server that keeps handing back a cursor is either huge or hostile; either way we
stop. Shared by both transports so the limits cannot drift apart.
"""

from __future__ import annotations

from typing import Any

from mcp import types

from ..errors import InventoryTooLarge
from ..models import Tool

MAX_PAGES = 50
MAX_TOOLS = 500


async def collect_tools(session: Any) -> list[Tool]:
    tools: list[Tool] = []
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
        result = await session.list_tools(params=params)
        for t in result.tools:
            tools.append(
                Tool(
                    name=t.name,
                    description=getattr(t, "description", None) or "",
                    input_schema=getattr(t, "input_schema", None)
                    or getattr(t, "inputSchema", None)
                    or {"type": "object"},
                )
            )
        if len(tools) > MAX_TOOLS:
            raise InventoryTooLarge(f"Server advertises more than {MAX_TOOLS} tools; refusing.")
        cursor = getattr(result, "next_cursor", None) or getattr(result, "nextCursor", None)
        if not cursor:
            return tools
    raise InventoryTooLarge(f"tools/list kept paginating past {MAX_PAGES} pages; refusing.")
