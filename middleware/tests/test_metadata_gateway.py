import asyncio
import base64
import socket
from unittest.mock import AsyncMock

import pytest

from homelab import metadata_proxy as proxy


def header(host="ws.audioscrobbler.com", port=443, key="k" * 43):
    auth = base64.b64encode(("aurral:" + key).encode()).decode()
    return f"CONNECT {host}:{port} HTTP/1.1\r\nProxy-Authorization: Basic {auth}\r\n\r\n".encode()


@pytest.mark.parametrize("host", sorted(proxy.ALLOWED))
def test_explicit_metadata_origins_require_authentication(host):
    assert proxy.target(header(host), "k" * 43) == host
    with pytest.raises(ValueError):
        proxy.target(header(host), "wrong-key")


@pytest.mark.parametrize("host", ["api.listenbrainz.org", "labs.api.listenbrainz.org", "localhost", "navidrome", "169.254.169.254", "ws.audioscrobbler.com.attacker.test", "ws.audioscrobbler.com@127.0.0.1"])
def test_other_destinations_are_denied(host):
    with pytest.raises(ValueError):
        proxy.target(header(host), "k" * 43)


def test_no_arbitrary_http_ports_or_request_body():
    for request in (header(port=80), header().replace(b"CONNECT", b"POST"),
                    header().replace(b"\r\n\r\n", b"\r\nTransfer-Encoding: chunked\r\n\r\n")):
        with pytest.raises(ValueError):
            proxy.target(request, "k" * 43)


def test_dns_private_addresses_denied_and_checked_public_address_is_pinned(monkeypatch):
    async def run():
        loop = asyncio.get_running_loop()
        resolver = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
        monkeypatch.setattr(loop, "getaddrinfo", resolver)
        connect = AsyncMock(return_value=("reader", "writer"))
        monkeypatch.setattr(asyncio, "open_connection", connect)
        with pytest.raises(ValueError):
            await proxy.connect_public("ws.audioscrobbler.com")
        connect.assert_not_called()
        resolver.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        assert await proxy.connect_public("ws.audioscrobbler.com") == ("reader", "writer")
        connect.assert_awaited_once_with("8.8.8.8", 443, family=socket.AF_INET)
    asyncio.run(run())
