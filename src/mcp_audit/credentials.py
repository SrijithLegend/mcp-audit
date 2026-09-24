"""Where a Cloud token lives on disk.

No keyring dependency in the engine: `keyring` drags platform backends into a
package people install with `uvx`. If it is already importable we use it, otherwise
a 0600 file. Either way the token is never logged and never sent anywhere but our
own API.
"""

from __future__ import annotations

import os
from pathlib import Path

SERVICE = "mcp-audit"
ENV_VAR = "MCP_AUDIT_TOKEN"
WEB = os.environ.get("MCP_AUDIT_WEB", "https://mcpaudit.dev")


def token_page() -> str:
    return f"{WEB}/app/settings/tokens"


def path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / "mcp-audit" / "credentials"


def store(token: str) -> Path:
    try:
        import keyring  # type: ignore[import-not-found]

        keyring.set_password(SERVICE, "token", token)
        return Path("system keyring")
    except Exception:
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(token + "\n", encoding="utf-8")
        target.chmod(0o600)
        return target


def load() -> str | None:
    if os.environ.get(ENV_VAR):
        return os.environ[ENV_VAR]
    try:
        import keyring

        found: str | None = keyring.get_password(SERVICE, "token")
        if found:
            return found
    except Exception:
        pass
    target = path()
    if target.exists():
        return target.read_text(encoding="utf-8").strip() or None
    return None
