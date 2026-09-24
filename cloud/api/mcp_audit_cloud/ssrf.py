"""SSRF guard for remote targets (docs/SECURITY.md §3).

A user hands us a URL and we connect to it from inside our own network. That is the
single most dangerous thing this service does, so the rules are absolute:

- `https` only, port 443 (8443 behind a flag).
- Resolve the hostname **once**; reject if *any* resolved address is private, loopback,
  link-local, CGNAT, unique-local, reserved, multicast, or cloud metadata.
- **Pin the connection to the address we validated.** A transport that re-resolves would
  reopen DNS rebinding, so we connect to the IP and carry the original Host and SNI.
- No redirects. A redirect is an error, not a convenience.
- Byte cap and timeouts, reused from the engine's capture layer.

In production the workers' egress also goes through a proxy that denies private ranges
independently -- if this file has a bug, that is the second wall.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlsplit

import httpx2 as httpx
from mcp_audit.capture.http import MAX_RESPONSE_BYTES, CappedTransport
from mcp_audit.errors import CaptureError

ALLOWED_PORTS = frozenset({443})
ALLOWED_PORTS_WITH_FLAG = frozenset({443, 8443})

#: Addresses that are never a customer's MCP server, whatever DNS says.
BLOCKED_EXACT = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),  # AWS/GCP/Azure IMDS
        ipaddress.ip_address("100.100.100.200"),  # Alibaba metadata
        ipaddress.ip_address("fd00:ec2::254"),  # AWS IMDS over IPv6
    }
)
BLOCKED_NETS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",  # CGNAT
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "255.255.255.255/32",
        "::/128",
        "::1/128",
        "fc00::/7",  # unique local
        "fe80::/10",  # link local
        "ff00::/8",  # multicast
        "2001:db8::/32",
    )
)


class SsrfError(CaptureError):
    """The URL is not one we are willing to connect to. Message is user-visible."""


def is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if this address must never be dialled.

    `ipaddress`'s own properties catch most of it; the explicit list catches metadata
    endpoints, which are globally routable in the eyes of the stdlib.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        # ::ffff:127.0.0.1 is loopback wearing a hat
        return is_blocked(ip.ipv4_mapped)
    if ip in BLOCKED_EXACT:
        return True
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True
    return any(ip in net for net in BLOCKED_NETS)


def resolve(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SsrfError(f"Cannot resolve {host}.") from exc
    addresses = []
    for info in infos:
        try:
            addresses.append(ipaddress.ip_address(info[4][0]))
        except ValueError:  # pragma: no cover - getaddrinfo returned something odd
            continue
    if not addresses:
        raise SsrfError(f"Cannot resolve {host}.")
    return addresses


def validate(url: str, allow_8443: bool = False) -> tuple[str, ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Returns (hostname, the one address we will connect to).

    Rejects if *any* resolved address is blocked -- not just the first. A hostname with
    one public and one private A record is an attack, not a misconfiguration.
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise SsrfError("Remote targets must be https://.")
    if not parts.hostname:
        raise SsrfError("That URL has no hostname.")
    if "@" in (parts.netloc or ""):
        raise SsrfError("Credentials in the URL are not supported; use a header.")
    port = parts.port or 443
    allowed = ALLOWED_PORTS_WITH_FLAG if allow_8443 else ALLOWED_PORTS
    if port not in allowed:
        raise SsrfError(f"Port {port} is not allowed (allowed: {sorted(allowed)}).")

    host = parts.hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if is_blocked(literal):
            raise SsrfError(f"{host} is not a public address.")
        return host, literal

    addresses = resolve(host)
    blocked = [str(a) for a in addresses if is_blocked(a)]
    if blocked:
        raise SsrfError(f"{host} resolves to a non-public address ({blocked[0]}).")
    return host, addresses[0]


class PinnedTransport(httpx.AsyncHTTPTransport):
    """Connects to one validated IP while presenting the original host and SNI.

    This is what actually defeats DNS rebinding: the check above and the connection
    below cannot disagree, because the address is not looked up twice.
    """

    def __init__(self, host: str, ip: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._host = host
        self._ip = ip

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host != self._host:
            # Only possible if something re-targeted the request mid-flight.
            raise SsrfError(f"Refusing to connect to {request.url.host}: not the validated host.")
        pinned = request.url.copy_with(host=self._ip)
        request.url = pinned
        request.headers["Host"] = self._host
        request.extensions = {**request.extensions, "sni_hostname": self._host}
        return await super().handle_async_request(request)


def guarded_client(
    url: str,
    headers: dict[str, str] | None = None,
    allow_8443: bool = False,
    limit: int = MAX_RESPONSE_BYTES,
) -> httpx.AsyncClient:
    """A client that can only talk to the one address we validated for this URL."""
    host, ip = validate(url, allow_8443=allow_8443)
    transport = CappedTransport(PinnedTransport(host=host, ip=str(ip)), limit=limit)
    return httpx.AsyncClient(
        headers=headers or {},
        timeout=httpx.Timeout(15.0, connect=5.0),
        follow_redirects=False,
        transport=transport,
    )
