"""Bounded-latency revocation of an already open response body.

A revoked session or a withdrawn track permission ends the transfer within about half a
second (local) or five seconds (Navidrome). A check that merely could not be answered --
the session database busy for a moment with another writer, Navidrome slow or briefly
unreachable -- is not a revocation: the song keeps playing, and only if the answer stays
unknown for longer than the grace period does the transfer fail closed.
"""
import asyncio
import hashlib
import logging
import secrets
import time

import httpx
from fastapi import HTTPException

import db

LOCAL_GRACE = 5.0    # seconds the local session check may stay unanswerable
REMOTE_GRACE = 20.0  # seconds the remote permission check may stay unanswerable
_DENIED = {401, 403, 404}

log = logging.getLogger("armonia.playback")
if not log.handlers:
    # One line per audio response, without accounts, addresses or media identifiers.
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s: %(name)s %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def playback_id() -> str:
    """A short random correlation id, shared by the response header and the log line."""
    return secrets.token_hex(4)


def media_tag(ident: str) -> str:
    """A stable, non-reversible label so lines about the same song can be grouped."""
    return hashlib.sha256(ident.encode()).hexdigest()[:8]


class Observation:
    """What one audio response did, logged once when it ends."""

    def __init__(self, pid, kind, media, source, start=0, end=None, clock=time.monotonic):
        self.pid, self.kind, self.media, self.source = pid, kind, media, source
        self.start, self.end, self.clock = start, end, clock
        self.opened = clock()
        self.first = None
        self.sent = 0
        self.outcome = "complete"
        self.soft = 0  # checks that could not be answered and were tolerated
        self.detail = ""  # how it was sent (light copy, rates), appended to the line

    def finish(self):
        elapsed = self.clock() - self.opened
        first = f"{(self.first - self.opened) * 1000:.0f}" if self.first is not None else "-"
        expected = f"{self.end - self.start + 1}" if self.end is not None else "?"
        level = logging.WARNING if self.outcome.startswith("aborted") else logging.INFO
        log.log(level, "id=%s kind=%s media=%s source=%s range=%s-%s sent=%s/%s first_ms=%s secs=%.1f soft=%s outcome=%s%s",
                self.pid, self.kind, self.media, self.source, self.start,
                self.end if self.end is not None else "", self.sent, expected, first, elapsed, self.soft, self.outcome,
                " " + self.detail if self.detail else "")


async def guarded(iterator, session, clock=time.monotonic, remote_check=None, remote_checked=False,
                  observe: Observation | None = None):
    next_check = 0
    next_remote = clock() + 5 if remote_checked else 0
    local_unknown = remote_unknown = None
    try:
        async for block in iterator:
            now = clock()
            if now >= next_check:
                # One small read per half-second, independent of media bitrate. A plain
                # read: no write lock competing with imports or downloads twice a second.
                try:
                    await asyncio.to_thread(db.check_session, session)
                    local_unknown = None
                except HTTPException as exc:
                    if exc.status_code != 503:
                        raise
                    local_unknown = now if local_unknown is None else local_unknown
                    if observe:
                        observe.soft += 1
                    if now - local_unknown >= LOCAL_GRACE:
                        raise
                next_check = now + .5
            if remote_check and now >= next_remote:
                try:
                    await asyncio.wait_for(remote_check(), timeout=3)
                    remote_unknown = None
                except HTTPException as exc:
                    if exc.status_code in _DENIED:
                        raise RuntimeError("audio transfer interrupted") from None
                    remote_unknown = _tolerate(remote_unknown, now, observe)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in _DENIED:
                        raise RuntimeError("audio transfer interrupted") from None
                    remote_unknown = _tolerate(remote_unknown, now, observe)
                except (httpx.HTTPError, TimeoutError, ValueError, KeyError, AttributeError):
                    remote_unknown = _tolerate(remote_unknown, now, observe)
                next_remote = now + 5
            if observe:
                if observe.first is None:
                    observe.first = observe.clock()
                observe.sent += len(block)
            yield block
    except HTTPException as exc:
        # Abort even chunked responses: a revoked transfer must not be accepted
        # as a complete offline download when no Content-Length was available.
        if observe:
            observe.outcome = f"aborted:session-{exc.status_code}"
        raise RuntimeError("audio transfer interrupted") from None
    except httpx.HTTPError as exc:
        # Abort even an unknown-length transfer; a truncated source must not
        # look like a successfully completed offline download. Hide signed URLs.
        if observe:
            observe.outcome = f"aborted:source-{type(exc).__name__}"
        raise RuntimeError("audio transfer interrupted") from None
    except RuntimeError:
        if observe and observe.outcome == "complete":
            observe.outcome = "aborted:permission"
        raise
    except (asyncio.CancelledError, GeneratorExit):
        # The player closed the connection: a seek, a skip, a full buffer or a lost network.
        if observe:
            observe.outcome = "client-closed"
        raise
    finally:
        try:
            await iterator.aclose()
        finally:
            if observe:
                observe.finish()


def _tolerate(since, now, observe):
    since = now if since is None else since
    if observe:
        observe.soft += 1
    if now - since >= REMOTE_GRACE:
        if observe:
            observe.outcome = "aborted:permission-unverifiable"
        raise RuntimeError("audio transfer interrupted")
    return since
