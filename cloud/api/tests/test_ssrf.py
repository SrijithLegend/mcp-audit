"""The SSRF test table from docs/SECURITY.md §3. Every row must be rejected.

This is the file to read if you want to know whether the Cloud can be made to fetch
something it should not. Adding a row here is cheaper than an incident.
"""

from __future__ import annotations

import ipaddress

import pytest

from mcp_audit_cloud.ssrf import PinnedTransport, SsrfError, guarded_client, is_blocked, validate

REJECTED = [
    ("http scheme", "http://example.com/mcp"),
    ("no scheme", "example.com/mcp"),
    ("file scheme", "file:///etc/passwd"),
    ("gopher", "gopher://example.com/"),
    ("loopback v4", "https://127.0.0.1/mcp"),
    ("loopback name", "https://localhost/mcp"),
    ("loopback v6", "https://[::1]/mcp"),
    ("all zeros", "https://0.0.0.0/mcp"),
    ("decimal ip", "https://2130706433/mcp"),
    ("private 10", "https://10.0.0.5/mcp"),
    ("private 172", "https://172.16.0.5/mcp"),
    ("private 192", "https://192.168.1.1/mcp"),
    ("cgnat", "https://100.64.0.1/mcp"),
    ("link local", "https://169.254.0.1/mcp"),
    ("aws metadata", "https://169.254.169.254/latest/meta-data/"),
    ("alibaba metadata", "https://100.100.100.200/"),
    ("aws metadata v6", "https://[fd00:ec2::254]/"),
    ("unique local v6", "https://[fc00::1]/mcp"),
    ("link local v6", "https://[fe80::1]/mcp"),
    ("ipv4-mapped loopback", "https://[::ffff:127.0.0.1]/mcp"),
    ("ipv4-mapped private", "https://[::ffff:10.0.0.1]/mcp"),
    ("multicast", "https://224.0.0.1/mcp"),
    ("reserved", "https://240.0.0.1/mcp"),
    ("broadcast", "https://255.255.255.255/mcp"),
    ("odd port", "https://example.com:8080/mcp"),
    ("odd port 22", "https://example.com:22/mcp"),
    ("credentials in url", "https://user:pass@example.com/mcp"),
    ("no host", "https:///mcp"),
]


@pytest.mark.parametrize("name,url", REJECTED, ids=[n for n, _ in REJECTED])
def test_rejected(name, url):
    with pytest.raises(SsrfError):
        validate(url)


def test_a_public_https_url_is_accepted():
    host, ip = validate("https://example.com/mcp")
    assert host == "example.com"
    assert not is_blocked(ip)


def test_a_public_literal_ip_is_accepted():
    _host, ip = validate("https://93.184.216.34/mcp")
    assert str(ip) == "93.184.216.34"


def test_8443_only_behind_the_flag():
    with pytest.raises(SsrfError):
        validate("https://example.com:8443/mcp")
    host, _ = validate("https://example.com:8443/mcp", allow_8443=True)
    assert host == "example.com"


def test_a_hostname_resolving_to_private_is_rejected(monkeypatch):
    """The DNS case: the URL looks fine, the resolution does not."""
    monkeypatch.setattr("mcp_audit_cloud.ssrf.resolve", lambda host: [ipaddress.ip_address("10.1.2.3")])
    with pytest.raises(SsrfError, match="non-public"):
        validate("https://internal.evil.example/mcp")


def test_any_private_answer_rejects_the_whole_name(monkeypatch):
    """One public and one private A record is an attack, not a misconfiguration."""
    monkeypatch.setattr(
        "mcp_audit_cloud.ssrf.resolve",
        lambda host: [ipaddress.ip_address("93.184.216.34"), ipaddress.ip_address("127.0.0.1")],
    )
    with pytest.raises(SsrfError):
        validate("https://rebind.evil.example/mcp")


def test_unresolvable_host_is_an_error(monkeypatch):
    import socket

    def boom(*_args, **_kwargs):
        raise socket.gaierror("nope")

    monkeypatch.setattr("socket.getaddrinfo", boom)
    with pytest.raises(SsrfError, match="Cannot resolve"):
        validate("https://does-not-exist.invalid/mcp")


async def test_the_connection_is_pinned_to_the_validated_address(monkeypatch):
    """Rebinding defence: the transport dials the IP we checked, not a fresh lookup."""
    seen: dict[str, str] = {}

    async def fake_handle(self, request):
        seen["url_host"] = request.url.host
        seen["host_header"] = request.headers["Host"]
        seen["sni"] = request.extensions.get("sni_hostname", "")
        import httpx2 as httpx

        return httpx.Response(200, content=b"{}")

    monkeypatch.setattr("httpx2.AsyncHTTPTransport.handle_async_request", fake_handle)
    monkeypatch.setattr("mcp_audit_cloud.ssrf.resolve", lambda host: [ipaddress.ip_address("93.184.216.34")])
    client = guarded_client("https://example.com/mcp")
    try:
        await client.post("https://example.com/mcp", content=b"{}")
    finally:
        await client.aclose()
    assert seen["url_host"] == "93.184.216.34"
    assert seen["host_header"] == "example.com"
    assert seen["sni"] == "example.com"


async def test_the_transport_refuses_a_retargeted_request():
    import httpx2 as httpx

    transport = PinnedTransport(host="example.com", ip="93.184.216.34")
    with pytest.raises(SsrfError, match="not the validated host"):
        await transport.handle_async_request(httpx.Request("GET", "https://evil.example/"))


def test_the_client_never_follows_a_redirect(monkeypatch):
    monkeypatch.setattr("mcp_audit_cloud.ssrf.resolve", lambda host: [ipaddress.ip_address("93.184.216.34")])
    client = guarded_client("https://example.com/mcp")
    # A 301 to an internal address is the classic bypass; not following it is the fix.
    assert client.follow_redirects is False


async def test_an_oversized_body_is_aborted(monkeypatch):
    """The response cap, on the streaming path rather than content-length."""
    import httpx2 as httpx
    from mcp_audit.errors import CaptureError

    class Flood:
        async def __aiter__(self):
            for _ in range(10):
                yield b"x" * 1024

        async def aclose(self):
            return None

    async def fake_handle(self, request):
        return httpx.Response(200, stream=Flood(), headers={"content-type": "application/json"})

    monkeypatch.setattr("httpx2.AsyncHTTPTransport.handle_async_request", fake_handle)
    monkeypatch.setattr("mcp_audit_cloud.ssrf.resolve", lambda host: [ipaddress.ip_address("93.184.216.34")])
    client = guarded_client("https://example.com/mcp", limit=2048)
    try:
        with pytest.raises(CaptureError, match="exceeded"):
            response = await client.send(client.build_request("GET", "https://example.com/mcp"), stream=True)
            async for _ in response.aiter_bytes():
                pass
    finally:
        await client.aclose()


async def test_a_declared_oversized_body_is_refused_before_reading(monkeypatch):
    import httpx2 as httpx
    from mcp_audit.errors import CaptureError

    async def fake_handle(self, request):
        return httpx.Response(200, content=b"{}", headers={"content-length": "99999999"})

    monkeypatch.setattr("httpx2.AsyncHTTPTransport.handle_async_request", fake_handle)
    monkeypatch.setattr("mcp_audit_cloud.ssrf.resolve", lambda host: [ipaddress.ip_address("93.184.216.34")])
    client = guarded_client("https://example.com/mcp", limit=1024)
    try:
        with pytest.raises(CaptureError, match="advertised"):
            await client.get("https://example.com/mcp")
    finally:
        await client.aclose()
