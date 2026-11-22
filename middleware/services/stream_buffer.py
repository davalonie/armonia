"""Whole-song memory buffer for external streams, private to each user.

A song is only a few megabytes and the provider serves ranged chunks far faster than
real time, so the complete file is fetched once (about a second) and every later byte
range -- the first bytes, a seek, a replay -- is answered from memory instead of opening
a new provider connection. Nothing is written to disk and nothing outlives the idle time.
"""
import asyncio
import os
import time
from dataclasses import dataclass, field

import httpx

from services.preview_stream import READ_SIZE, relay_ranged

IDLE_SECONDS = 20 * 60
PER_USER = 6
# A failed provider chunk is asked for again from the first missing byte, a bounded
# number of times, before the song is given up: one dropped connection must not cut a
# song that is already playing. A refused location (4xx) is not retried here.
FILL_ATTEMPTS = 3
RETRY_DELAYS = (0.5, 1.5)


def limits():
    """(total bytes, bytes per song); MUSIC_STREAM_BUFFER_MAX_BYTES=0 switches the buffer off."""
    try:
        total = max(0, int(os.environ.get("MUSIC_STREAM_BUFFER_MAX_BYTES", str(160 * 1024**2))))
    except ValueError:
        total = 160 * 1024**2
    return total, min(total, 32 * 1024**2)


@dataclass
class Song:
    total: int
    content_type: str
    data: bytearray = field(default_factory=bytearray)
    error: bool = False
    touched: float = field(default_factory=time.monotonic)
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task | None = None
    retries: int = 0
    readers: int = 0  # open responses reading this song; it is never evicted under them

    @property
    def complete(self):
        return len(self.data) >= self.total

    async def read(self, start, end):
        """Bytes start..end inclusive, as soon as each block has arrived."""
        position = start
        self.readers += 1
        try:
            async for block in self._read(position, end):
                yield block
        finally:
            self.readers -= 1
            self.touched = time.monotonic()

    async def _read(self, position, end):
        while position <= end:
            self.touched = time.monotonic()
            if len(self.data) <= position:
                async with self.changed:
                    await self.changed.wait_for(lambda p=position: len(self.data) > p or self.error)
                if len(self.data) <= position:
                    raise httpx.RemoteProtocolError("buffered audio source failed")
            stop = min(end + 1, len(self.data), position + READ_SIZE)
            yield bytes(self.data[position:stop])
            position = stop


_songs: dict[tuple[str, str], Song] = {}


def _drop(key):
    song = _songs.pop(key, None)
    if song and song.task and not song.task.done():
        song.task.cancel()


def _make_room(owner, size):
    total, _ = limits()
    now = time.monotonic()
    for key, song in list(_songs.items()):
        if not song.readers and (now - song.touched > IDLE_SECONDS or (song.error and not song.data)):
            _drop(key)
    # A song somebody is listening to is not a candidate: evicting it would cancel its
    # download under the player. Without enough room the caller relays directly instead.
    oldest = sorted(((k, s) for k, s in _songs.items() if not s.readers), key=lambda entry: entry[1].touched)
    mine = [key for key, _ in oldest if key[0] == owner]
    for key in mine[:max(0, len(mine) - PER_USER + 1)]:
        _drop(key)
    for key, _ in oldest:
        if sum(s.total for s in _songs.values()) + size <= total:
            break
        _drop(key)
    return sum(s.total for s in _songs.values()) + size <= total


def get(owner, ident):
    song = _songs.get((owner, ident))
    if song is None:
        return None
    if song.error or time.monotonic() - song.touched > IDLE_SECONDS:
        _drop((owner, ident))  # A failed fetch is retried from the provider, never served half-way.
        return None
    song.touched = time.monotonic()
    return song


def start(owner, ident, url, headers, total, content_type):
    """Begin fetching the whole song for this user. None when it does not fit the limits."""
    existing = get(owner, ident)
    if existing:
        return existing
    _, single = limits()
    if not total or total > single or not _make_room(owner, total):
        return None
    song = Song(total=total, content_type=content_type)

    async def fill():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=60.0), follow_redirects=False,
                                         trust_env=False) as client:
                for attempt in range(FILL_ATTEMPTS):
                    try:
                        async for block in relay_ranged(client, url, headers, len(song.data), total - 1):
                            song.data.extend(block)
                            async with song.changed:
                                song.changed.notify_all()
                        break
                    except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                        if attempt + 1 >= FILL_ATTEMPTS or (status is not None and status < 500 and status != 429):
                            raise
                        song.retries += 1
                        await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
            if not song.complete:
                song.error = True
        except (httpx.HTTPError, OSError):
            song.error = True
        except asyncio.CancelledError:
            song.error = True
            raise
        finally:
            async with song.changed:
                song.changed.notify_all()

    song.task = asyncio.create_task(fill())
    _songs[owner, ident] = song
    return song


def forget(owner=None):
    for key in [k for k in _songs if owner is None or k[0] == owner]:
        _drop(key)
