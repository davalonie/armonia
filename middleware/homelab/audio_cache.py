"""Bounded, optional cache for administrator-authorized HTTP audio only."""
import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path

import httpx
from fastapi import HTTPException

from config import MUSIC_DIR
from services.safe_files import directory, run_blocking

_guard = asyncio.Lock()
_fetch_slots = asyncio.Semaphore(2)
_inflight = set()
_NAMES = re.compile(r"^[a-f0-9]{64}\.(audio|json)$")
_AUDIO_TYPES = {"audio/mpeg", "audio/mp4", "audio/aac", "audio/flac", "audio/x-flac", "audio/wav", "audio/x-wav", "audio/ogg", "audio/webm", "application/ogg"}


class TooLarge(Exception):
    pass


def root():
    value = os.environ.get("MUSIC_CACHE_DIR")
    if not value:
        return None
    path = Path(value)
    music = Path(MUSIC_DIR).resolve()
    resolved = path.resolve()
    if not path.is_absolute() or resolved == music or music in resolved.parents or resolved in music.parents:
        raise RuntimeError("cache and permanent library must be separate")
    with directory(path, create=True):
        pass
    return path


def limits():
    quota = max(0, int(os.environ.get("MUSIC_CACHE_MAX_BYTES", str(256 * 1024**2))))
    single = min(quota, 16 * 1024**2)
    ttl = max(0, int(os.environ.get("MUSIC_CACHE_TTL_SECONDS", "86400")))
    return quota, single, ttl


def read_bytes(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        value = f.read(limit + 1)
    if len(value) > limit:
        raise TooLarge()
    return value


def atomic(path, value):
    temp = path.parent / (".cache-" + uuid.uuid4().hex)
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def cleanup(reserve=0):
    folder = root()
    if folder is None:
        return
    quota, _, _ = limits()
    now, entries, size = time.time(), [], 0
    for file in folder.iterdir():
        if re.fullmatch(r"\.cache-[a-f0-9]{32}", file.name):
            file.unlink(missing_ok=True)  # Called only while the writer lock is held.
            continue
        if not _NAMES.fullmatch(file.name):
            continue
        if file.is_symlink():
            file.unlink()
            continue
        if file.suffix != ".audio":
            if not file.with_suffix(".audio").exists():
                file.unlink(missing_ok=True)
            continue
        meta = file.with_suffix(".json")
        try:
            data = json.loads(read_bytes(meta, 2048))
            if data["expires"] <= now:
                raise ValueError("expired")
            amount = file.stat().st_size
            entries.append((data["accessed"], file, meta, amount))
            size += amount
        except (ValueError, OSError, KeyError, TooLarge):
            file.unlink(missing_ok=True)
            meta.unlink(missing_ok=True)
    count = len(entries)
    for _, file, meta, amount in sorted(entries):
        if size + reserve <= quota and count < (1000 if reserve else 1001):
            break
        file.unlink(missing_ok=True)
        meta.unlink(missing_ok=True)
        size -= amount
        count -= 1


async def _fetch(url, maximum):
    async with asyncio.timeout(90):
        async with httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if mime not in _AUDIO_TYPES:
                    raise HTTPException(502, "source did not return a supported audio format")
                if int(response.headers.get("Content-Length", "0")) > maximum:
                    raise TooLarge()
                body = bytearray()
                async for chunk in response.aiter_bytes(64 * 1024):
                    body.extend(chunk)
                    if len(body) > maximum:
                        raise TooLarge()
                if not body:
                    raise HTTPException(502, "empty audio source")
                return bytes(body), mime


async def fetch(url, maximum):
    try:
        return await _fetch(url, maximum)
    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
        raise HTTPException(502, "authorized audio source unavailable") from exc


def _read_cached(audio, meta, maximum):
    cleanup()
    metadata = json.loads(read_bytes(meta, 2048))
    data = read_bytes(audio, maximum)
    metadata["accessed"] = time.time()
    atomic(meta, json.dumps(metadata).encode())
    return data, metadata["mime"]


def _write_cached(audio, meta, data, mime, ttl):
    cleanup(reserve=len(data))
    atomic(audio, data)
    atomic(meta, json.dumps({"mime": mime, "expires": time.time() + ttl, "accessed": time.time()}).encode())


async def get(user, reference, url):
    folder = root()
    quota, maximum, ttl = limits()
    if folder is None or quota == 0 or ttl == 0:
        return None
    key = hashlib.sha256(f"{user}\n{reference}\n{url}".encode()).hexdigest()
    audio, meta = folder / (key + ".audio"), folder / (key + ".json")
    async with _guard:
        try:
            return await run_blocking(_read_cached, audio, meta, maximum)
        except (OSError, ValueError, KeyError, TooLarge):
            pass
        # A slow miss must not block a hit or another user's playback. When
        # both cache fill slots are busy, use the existing streaming transport.
        if key in _inflight or _fetch_slots.locked():
            return None
        _inflight.add(key)
        await _fetch_slots.acquire()
    try:
        try:
            data, mime = await fetch(url, maximum)
        except TooLarge:
            return None
        async with _guard:
            try:
                await run_blocking(_write_cached, audio, meta, data, mime, ttl)
            except OSError:
                # Disk full affects optional caching, not the audio already read.
                logging.getLogger(__name__).warning("audio cache write deferred")
        return data, mime
    finally:
        _inflight.discard(key)
        _fetch_slots.release()


async def worker():
    while True:
        try:
            async with _guard:
                await run_blocking(cleanup)
        except (OSError, ValueError, RuntimeError):
            logging.getLogger(__name__).warning("audio cache cleanup deferred")
        await asyncio.sleep(60)
