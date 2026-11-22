"""Optional internal CONNECT gateway for the pinned Aurral metadata clients.

TLS remains end to end. This restricts destinations, not encrypted HTTP methods
or payloads. No ListenBrainz, Last.fm user sessions, or general-purpose proxy.
"""
import asyncio
import base64
import ipaddress
import logging
import os
import secrets
import socket
from contextlib import suppress
from pathlib import Path

ALLOWED = frozenset({"ws.audioscrobbler.com", "api.deezer.com", "musicbrainz.org", "lidarrapi.brainzmash.cc"})
_slots = asyncio.Semaphore(16)
log = logging.getLogger(__name__)


def target(header, credential):
    """Accept one authenticated CONNECT to a fixed HTTPS metadata origin."""
    lines = header.decode("ascii").split("\r\n")
    method, authority, protocol = lines[0].split(" ")
    if method != "CONNECT" or protocol not in {"HTTP/1.0", "HTTP/1.1"}:
        raise ValueError("CONNECT required")
    host, port = authority.split(":")
    if host not in ALLOWED or port != "443":
        raise ValueError("destination denied")
    headers = {}
    for line in lines[1:]:
        if not line:
            continue
        key, value = line.split(":", 1)
        key = key.lower()
        if key in headers:
            raise ValueError("duplicate header")
        headers[key] = value.strip()
    expected = "Basic " + base64.b64encode(("aurral:" + credential).encode()).decode()
    if not secrets.compare_digest(headers.get("proxy-authorization", ""), expected):
        raise ValueError("authentication required")
    if headers.get("content-length", "0") != "0" or "transfer-encoding" in headers:
        raise ValueError("unexpected body")
    return host


async def connect_public(host):
    # Resolve once and connect to that literal address; DNS cannot switch the
    # checked destination between validation and connect (rebinding).
    addresses = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    public = []
    for family, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        if not ip.is_global:
            raise ValueError("non-public metadata address")
        public.append((family, str(ip)))
    for family, address in public:
        try:
            return await asyncio.wait_for(asyncio.open_connection(address, 443, family=family), 10)
        except (OSError, TimeoutError):
            continue
    raise OSError("metadata destination unavailable")


async def relay(reader, writer):
    count = 0
    while chunk := await asyncio.wait_for(reader.read(64 * 1024), 30):
        count += len(chunk)
        if count > 32 * 1024**2:
            raise ValueError("metadata connection limit")
        writer.write(chunk)
        await writer.drain()


async def handle(reader, writer, credential):
    remote = None
    accepted = False
    host = None
    try:
        if _slots.locked():
            raise ValueError("busy")
        async with _slots, asyncio.timeout(120):
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            if len(header) > 8192:
                raise ValueError("header too large")
            host = target(header, credential)
            upstream, remote = await connect_public(host)
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            accepted = True
            log.info("metadata connection allowed: %s", host)
            tasks = [asyncio.create_task(relay(reader, remote)), asyncio.create_task(relay(upstream, writer))]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except (ValueError, OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        if not accepted:
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        log.info("metadata connection denied or unavailable")
    finally:
        for stream in (remote, writer):
            if stream:
                stream.close()
                with suppress(OSError, TimeoutError):
                    await asyncio.wait_for(stream.wait_closed(), 2)


async def main():
    credential = Path(os.environ["MUSIC_METADATA_PROXY_KEY_FILE"]).read_text().strip()
    if len(credential) < 43:
        raise RuntimeError("metadata proxy requires a random 256-bit credential")
    server = await asyncio.start_server(lambda r, w: handle(r, w, credential), "0.0.0.0", 8002, limit=8192)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
