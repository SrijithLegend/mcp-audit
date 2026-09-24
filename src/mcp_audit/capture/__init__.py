"""Reading a server's inventory. Two transports, one shape out: `Inventory`.

`tools/list` and `initialize` are the only requests we ever send. Nothing in here
calls a tool (CLAUDE.md invariant 1).
"""

from .http import capture_http
from .stdio import capture_stdio

__all__ = ["capture_http", "capture_stdio"]
