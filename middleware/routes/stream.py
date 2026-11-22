import asyncio
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from auth import get_current_session
from config import NAVIDROME_URL
from services import low_quality, stream_pacing
from services.http_ranges import single_range
from services.low_quality import LOW_KBPS, LowStore, LowUnavailable
from services.mp4_light import Light, LightCache, NotLightened, lighten
from services.navidrome_client import auth_params
from services.session_stream import Observation, guarded, media_tag, playback_id
from services.stream_pacing import (
    START_MAX_BYTES,
    is_preload,
    mp4_header_end,
    on_mobile_data,
    paced,
    path_hint,
    rates,
    variant,
    wants_whole_file,
)

router = APIRouter()
log = logging.getLogger("armonia.light")

PASSTHROUGH_HEADERS = ("content-type", "content-length", "accept-ranges", "content-range")
LIGHT_SUFFIXES = {"m4a", "mp4", "m4b"}
_light = LightCache()
_low = LowStore()
# How long a request waits for its data-saving copy to be made (about 1.5 s for a 4-minute song); past it the app
# plays another variant this time and the copy, still being made, is ready for the next.
LOW_WAIT_SECONDS = 15
# The 96 kbit/s AAC copy of before (never used: it only applied to songs over 160 kbit/s). Apps that still ask
# for it get "not available now" and fall back to their light copy, never other bytes under that name.
RETIRED_VARIANTS = {"baja"}


@router.get("/api/stream/{track_id}")
async def stream(
    track_id: str, request: Request, sess: dict = Depends(get_current_session)
):
    params = {"id": track_id, **auth_params(sess["username"], sess["salt"], sess["token"])}
    requested = single_range(request.headers.get("range"))
    whole = wants_whole_file(request.headers)
    asked = "original" if whole else variant(request.headers)
    song = {}

    client = httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), trust_env=False, follow_redirects=False)
    async def current_track_access():
        result = await client.get(f"{NAVIDROME_URL}/rest/getSong", params=params)
        result.raise_for_status()
        body = result.json()["subsonic-response"]
        if body.get("status") != "ok" or not body.get("song"):
            raise HTTPException(403, "track access no longer permitted")
        song.update(body["song"])

    light = plan = low = upstream = None
    try:
        # Reject inaccessible tracks before sending response headers; periodic
        # checks below only handle a permission change during a valid stream.
        await asyncio.wait_for(current_track_access(), timeout=3)
        # Which bytes a variant is depends only on the song, never on this moment (see stream_pacing.VARIANTS):
        # a low copy for a song that is already small is its light copy, every time.
        if asked in RETIRED_VARIANTS:
            raise LowUnavailable("variant retired")
        if asked == "ahorro":
            if not low_quality.applicable(song):
                raise LowUnavailable("no copy for this song")
            low = await _low_copy(params, track_id, song)
        elif asked == "ligera":
            light = await _light_for(client, params, track_id, song)
        if low is not None:
            plan = _plan_file(low, requested)
        elif light is not None:
            plan = _plan(light, song["size"], requested)
            upstream = None
            if plan.upstream_range:
                upstream = await client.send(client.build_request(
                    "GET", f"{NAVIDROME_URL}/rest/stream", params=params, headers={"Range": plan.upstream_range}),
                    stream=True)
                expected = f"bytes {plan.upstream_range.removeprefix('bytes=')}/{song['size']}"
                if upstream.status_code != 206 or upstream.headers.get("content-range") != expected:
                    await upstream.aclose()
                    raise ValueError("source did not honour the mapped range")
        else:
            upstream = await client.send(client.build_request(
                "GET", f"{NAVIDROME_URL}/rest/stream", params=params,
                headers={"Range": requested} if requested else {}), stream=True)
    except (httpx.HTTPError, TimeoutError, ValueError, KeyError, AttributeError):
        await client.aclose()
        raise HTTPException(503, "cannot verify current track access") from None
    except (LowUnavailable, OSError) as exc:  # TimeoutError is an OSError too: it stays above
        await client.aclose()
        log.info("low %s: not this time (%s)", media_tag(track_id), exc)
        raise HTTPException(503, "this variant is not available now") from None
    except BaseException:
        await client.aclose()
        raise

    async def relay():
        try:
            if low is not None:
                async for chunk in _file_part(low, plan.first, plan.last):
                    yield chunk
                return
            if plan is not None and plan.header_slice:
                yield plan.header_slice
            if upstream is not None:
                async for chunk in upstream.aiter_raw():
                    yield chunk
        finally:
            if upstream is not None:
                await upstream.aclose()
            await client.aclose()

    pid = playback_id()
    observe = Observation(pid, "download" if whole else "library", media_tag(track_id), "navidrome")
    served = "ahorro" if low is not None else "ligera" if light is not None else "original"
    if plan is not None:
        status = plan.status
        content_type = low_quality.CONTENT_TYPE if low is not None else str(song.get("contentType") or "audio/mp4")
        response_headers = {"content-type": content_type, "accept-ranges": "bytes",
                            "content-length": str(plan.last - plan.first + 1)}
        if plan.status == 206:
            response_headers["content-range"] = f"bytes {plan.first}-{plan.last}/{plan.total}"
        observe.start, observe.end = plan.first, plan.last
    else:
        status = upstream.status_code
        response_headers = {h: upstream.headers[h] for h in PASSTHROUGH_HEADERS if h in upstream.headers}
        if m := re.fullmatch(r"bytes (\d+)-(\d+)/\d+", upstream.headers.get("content-range", "")):
            observe.start, observe.end = int(m.group(1)), int(m.group(2))
        elif (length := upstream.headers.get("content-length", "")).isdigit():
            observe.end = int(length) - 1
    response_headers["Server-Timing"] = f'id;desc="{pid}"'
    response_headers["X-Armonia-Variante"] = served

    if whole:
        body = relay()
        observe.detail = "variant=original"
    else:
        hint = path_hint(request.headers)
        preload = is_preload(request.headers)
        fast, steady = rates(hint, LOW_KBPS if low is not None else song.get("bitRate"), preload=preload)
        header_end = (len(light.header) if light is not None
                      else _file_header_end(low) if low is not None else None)
        if light is None and low is None and 0 < observe.start < START_MAX_BYTES:
            # A song partly saved on the phone resumes from the middle of its header (a large embedded
            # cover): look at the file's first bytes to know how much of the header is still missing.
            header_end = await _header_end(client, params)
        audio_rate = None
        if on_mobile_data(request.headers):
            total = plan.total if plan is not None else int(song.get("size") or 0)
            seconds = float(song.get("duration") or 0)
            if total > 0 and seconds > 0:
                audio_rate = max(total - (header_end or 0), 1) / seconds
        body = paced(relay(), from_start=observe.start == 0, header_end=header_end, offset=observe.start,
                     rate_kbps=steady, fast_kbps=fast, audio_bytes_per_s=audio_rate,
                     ahead_s=stream_pacing.AHEAD_SECONDS if audio_rate else None)
        response_headers["X-Armonia-Ritmo"] = f"rapido={fast}; sostenido={steady}"
        observe.detail = (f"variant={served} fast={fast} steady={steady} hint={hint or '-'}"
                          + (" preload=1" if preload else "") + (" datos=1" if audio_rate else ""))
    return StreamingResponse(
        guarded(body, sess, remote_check=current_track_access, remote_checked=True, observe=observe),
        status_code=status,
        headers=response_headers,
    )


@dataclass(frozen=True)
class _Plan:
    """One response from the light copy: its range, what comes from the rebuilt header, and which
    bytes of the original file follow it."""
    first: int
    last: int
    total: int
    status: int
    header_slice: bytes
    upstream_range: str | None


def _span(total: int, requested: str | None) -> tuple[int, int, int]:
    """First and last byte of [requested] (one range, already validated) in a file of [total] bytes."""
    if requested is None:
        return 0, total - 1, 200
    a, b = requested.removeprefix("bytes=").split("-")
    if a == "":
        first, last = max(total - int(b), 0), total - 1
    else:
        first, last = int(a), min(int(b), total - 1) if b else total - 1
    if first >= total:
        raise HTTPException(416, "range not satisfiable")
    return first, last, 206


def _plan(light: Light, size: int, requested: str | None) -> _Plan:
    total = light.size(size)
    first, last, status = _span(total, requested)
    head = len(light.header)
    upstream_range = None
    if last >= head:
        upstream_range = f"bytes={max(first, head) + light.cut}-{last + light.cut}"
    return _Plan(first, last, total, status, light.header[first:last + 1] if first < head else b"", upstream_range)


def _plan_file(path: Path, requested: str | None) -> _Plan:
    total = path.stat().st_size
    first, last, status = _span(total, requested)
    return _Plan(first, last, total, status, b"", None)


async def _file_part(path: Path, first: int, last: int):
    with open(path, "rb") as source:
        source.seek(first)
        left = last - first + 1
        while left > 0:
            data = source.read(min(65_536, left))
            if not data:
                raise OSError("low copy shorter than announced")
            left -= len(data)
            yield data


def _file_header_end(path: Path) -> int | None:
    with open(path, "rb") as source:
        return mp4_header_end(source.read(64))


async def _low_copy(params, track_id, song) -> Path:
    """The song's data-saving copy on disk, made now if needed (LowUnavailable when not this time)."""
    size = song["size"]
    kept = _low.ready(track_id, size)
    if kept is not None:
        return kept
    started = time.monotonic()
    try:
        path = await asyncio.wait_for(_low.get(track_id, size, _fetcher(params, size)), timeout=LOW_WAIT_SECONDS)
        log.info("ahorro %s: made in %d ms", media_tag(track_id), (time.monotonic() - started) * 1000)
        return path
    except TimeoutError:
        raise LowUnavailable("still being made") from None
    except httpx.HTTPError as exc:
        raise LowUnavailable(type(exc).__name__) from None


def _fetcher(params, size):
    async def fetch(dest: Path):
        # Its own connection: the copy is still made if the request that asked for it goes away.
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), trust_env=False,
                                     follow_redirects=False) as source:
            async with source.stream("GET", f"{NAVIDROME_URL}/rest/stream", params=params) as response:
                if response.status_code != 200:
                    raise LowUnavailable(f"source answered {response.status_code}")
                written = 0
                with open(dest, "wb") as out:
                    async for chunk in response.aiter_raw():
                        written += len(chunk)
                        if written > size:
                            raise LowUnavailable("source sent more than the original")
                        out.write(chunk)
        if written != size:
            raise LowUnavailable("source sent part of the original")
    return fetch


class Prepare(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=3)


@router.post("/api/stream/preparar", status_code=202)
async def prepare(body: Prepare, sess: dict = Depends(get_current_session)):
    """The app saving data asks for the next songs of its queue: their copies are made now, behind any song
    someone is waiting for, so skipping to them starts at once. Only songs this account can play."""
    started = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), trust_env=False,
                                 follow_redirects=False) as client:
        for track_id in dict.fromkeys(body.ids):
            if not track_id or len(track_id) > 200:
                continue
            params = {"id": track_id, **auth_params(sess["username"], sess["salt"], sess["token"])}
            try:
                result = await client.get(f"{NAVIDROME_URL}/rest/getSong", params=params)
                song = result.json()["subsonic-response"]
                song = song.get("song") if song.get("status") == "ok" else None
            except (httpx.HTTPError, ValueError, KeyError):
                continue
            if song and low_quality.applicable(song):
                try:
                    _low.prepare(track_id, song["size"], _fetcher(params, song["size"]))
                    started += 1
                except OSError:
                    continue
    return Response(status_code=202, headers={"X-Armonia-Preparadas": str(started)})


async def _light_for(client, params, track_id, song) -> Light | None:
    """The rebuilt header for this song, or None when the song has none to rebuild (then the light copy is
    the original, every time). Raises when it cannot tell this time: serving the original instead would
    mix two different files under the app's key for the light copy."""
    size = song.get("size")
    if str(song.get("suffix") or "").lower() not in LIGHT_SUFFIXES or not isinstance(size, int) or size <= 0:
        return None
    key = (track_id, size)
    found, light = _light.get(key)
    if found:
        return light
    try:
        light = await asyncio.wait_for(_build_light(client, params, size), timeout=3)
    except NotLightened as exc:
        log.info("light %s: original (%s)", media_tag(track_id), exc)
        light = None
    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
        log.info("light %s: not this time (%s)", media_tag(track_id), type(exc).__name__)
        raise ValueError("light copy not available now") from None
    _light.put(key, light)
    return light


async def _read_exact(client, params, first, last, size) -> bytes:
    data = bytearray()
    async with client.stream("GET", f"{NAVIDROME_URL}/rest/stream", params=params,
                             headers={"Range": f"bytes={first}-{last}"}) as response:
        if response.status_code not in (200, 206):
            raise ValueError(f"source answered {response.status_code}")  # a bad moment, not the song
        if response.status_code != 206 or response.headers.get("content-range") != f"bytes {first}-{last}/{size}":
            raise NotLightened("source does not serve exact ranges of the original file")
        async for chunk in response.aiter_raw():
            data += chunk
            if len(data) > last - first + 1:
                raise NotLightened("source sent more than asked")
    if len(data) != last - first + 1:
        raise ValueError("short read")
    return bytes(data)


async def _build_light(client, params, size) -> Light:
    end = mp4_header_end(await _read_exact(client, params, 0, min(63, size - 1), size))
    if end is None:
        raise NotLightened("no MP4 header before the audio")
    return lighten(await _read_exact(client, params, 0, end - 1, size))


async def _header_end(client, params):
    """End of the MP4 header from the first 64 bytes of the file, or None. Never fails the request.

    Reads at most those bytes even if the source ignores the Range header."""
    async def first_bytes():
        head = b""
        async with client.stream("GET", f"{NAVIDROME_URL}/rest/stream", params=params,
                                 headers={"Range": "bytes=0-63"}) as response:
            if response.status_code not in (200, 206):
                return None
            async for chunk in response.aiter_raw():
                head += chunk
                if len(head) >= 64:
                    break
        return head[:64]
    try:
        head = await asyncio.wait_for(first_bytes(), timeout=2)
    except (httpx.HTTPError, TimeoutError):
        return None
    return mp4_header_end(head) if head else None
