"""Capture over Streamable HTTP. Used by the CLI directly, and by the Cloud
through its SSRF guard.

No process is spawned, so this is the only capture the Cloud is allowed to do
(CLAUDE.md invariant 3). The transport is handed an httpx client the caller owns:
in the CLI that is a plain client, in the Cloud it is one pinned to a
pre-validated IP address (SECURITY.md §3). The rule stays in one place -- this
module never decides what is safe to connect to, it just connects.
"""

from __future__ import annotations

from typing import Any

import anyio
import httpx2 as httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from ..errors import CaptureError, describe, first_leaf
from ..models import Inventory
from .paginate import collect_tools

TIMEOUT = 15.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def parse_headers(raw: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in raw or []:
        if ":" not in item:
            raise CaptureError(f"--header expects 'Name: value', got {item!r}")
        name, value = item.split(":", 1)
        out[name.strip()] = value.strip()
    return out


class CappedStream(httpx.AsyncByteStream):
    """Refuses to read past a byte budget.

    A server that answers `tools/list` with a gigabyte is not a server we are
    auditing, it is a server auditing our memory limits. Subclasses httpx's own
    stream type: the client asserts on it, and an SSE response is streamed.
    """

    def __init__(self, inner: Any, limit: int) -> None:
        self._inner = inner
        self._limit = limit

    async def __aiter__(self) -> Any:
        seen = 0
        async for chunk in self._inner:
            seen += len(chunk)
            if seen > self._limit:
                raise CaptureError(f"Server response exceeded {self._limit} bytes; aborted.")
            yield chunk

    async def aclose(self) -> None:
        aclose = getattr(self._inner, "aclose", None)
        if aclose is not None:
            await aclose()


class CappedTransport(httpx.AsyncBaseTransport):
    """Wraps any transport with the response cap. Composes with the Cloud's
    IP-pinned transport instead of replacing it."""

    def __init__(self, inner: httpx.AsyncBaseTransport, limit: int = MAX_RESPONSE_BYTES) -> None:
        self._inner = inner
        self._limit = limit

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        length = response.headers.get("content-length")
        if length and length.isdigit() and int(length) > self._limit:
            await response.aclose()
            raise CaptureError(f"Server response advertised {length} bytes (cap {self._limit}).")
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=CappedStream(response.stream, self._limit),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()


def http_client(
    headers: dict[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    **kwargs: Any,
) -> httpx.AsyncClient:
    """A client with our timeouts, no redirects, and a hard response cap.

    Redirects are an error, not a convenience: following one would move the
    connection to a host nobody validated.
    """
    return httpx.AsyncClient(
        headers=headers or {},
        timeout=httpx.Timeout(TIMEOUT, connect=5.0),
        follow_redirects=False,
        transport=CappedTransport(transport or httpx.AsyncHTTPTransport()),
        **kwargs,
    )


async def capture_http(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = TIMEOUT,
) -> Inventory:
    if not url.lower().startswith(("http://", "https://")):
        raise CaptureError(f"--url must be http(s), got {url!r}")
    owned = client is None
    api = client or http_client(headers)
    try:
        with anyio.fail_after(timeout):
            async with (
                streamable_http_client(url, http_client=api) as (read, write),
                ClientSession(read, write) as session,
            ):
                init = await session.initialize()
                tools = await collect_tools(session)
    except CaptureError:
        raise
    except Exception as exc:
        leaf = first_leaf(exc)
        if isinstance(leaf, TimeoutError):
            raise CaptureError(
                f"{url} did not respond to initialize + tools/list within {timeout:g}s."
            ) from exc
        raise CaptureError(f"Could not read {url}: {describe(leaf)}") from exc
    finally:
        if owned:
            await api.aclose()

    return Inventory.from_initialize(init, tools, url)
