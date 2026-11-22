import asyncio
import logging
import re
import time
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

import db
from auth import get_current_session
from config import DELETE_USERS, MUSIC_DIR, NAVIDROME_URL
from homelab import audio_cache, sources
from homelab.models import owner
from services import navidrome_client, safe_files, stream_buffer
from services.navidrome_client import auth_params
from services.preview_stream import (
    StreamInfoCache,
    parse_range,
    probe_upstream,
    relay_plain,
    relay_ranged,
    resolve_range,
)
from services.session_stream import Observation, guarded, media_tag, playback_id
from services.ytdlp_service import get_stream_info

router = APIRouter()
log = logging.getLogger(__name__)

_YT_VIDEO_ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')


_stream_info_cache = StreamInfoCache()
_stream_resolvers = {}
_resolution_slots = asyncio.Semaphore(2)


def _safe_stream(url: str, headers: dict) -> tuple[str, dict]:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if (parts.scheme != "https" or not host.endswith(".googlevideo.com")
            or parts.username or parts.password or parts.port not in (None, 443)):
        raise HTTPException(502, "unsupported audio origin")
    # Never carry cookies, authorization, or provider-specific credentials to
    # an extracted URL. Redirects are disabled as well.
    return url, {k: v for k, v in headers.items() if k.lower() in {"user-agent", "accept", "accept-language"}}


async def _extract_stream(video_id: str) -> tuple[str, dict]:
    cached = _stream_info_cache.get(video_id)
    if cached is not None:
        return _safe_stream(*cached)
    t0 = time.monotonic()
    try:
        url, headers = await asyncio.get_event_loop().run_in_executor(
            None, get_stream_info, video_id
        )
    except Exception as exc:
        # Log the detail server-side; don't leak yt-dlp internals (URLs/paths)
        # to the client.
        log.warning("preview %s: extraction failed (%s)", video_id, type(exc).__name__)
        raise HTTPException(status_code=502, detail="couldn't fetch preview") from exc
    log.info("preview %s: resolved stream in %.1fs", video_id, time.monotonic() - t0)
    url, headers = _safe_stream(url, headers)
    _stream_info_cache.put(video_id, url, headers)
    return url, headers


async def _resolve_stream(video_id: str) -> tuple[str, dict]:
    cached = _stream_info_cache.get(video_id)
    if cached is not None:
        return _safe_stream(*cached)
    task = _stream_resolvers.get(video_id)
    if task is None:
        if len(_stream_resolvers) >= 16:
            raise HTTPException(429, "audio resolution queue full")
        async def resolve():
            async with _resolution_slots:
                return await _extract_stream(video_id)
        task = asyncio.create_task(resolve())
        _stream_resolvers[video_id] = task
        def finished(done):
            if _stream_resolvers.get(video_id) is done:
                del _stream_resolvers[video_id]
            if not done.cancelled():
                done.exception()  # A disconnected client cannot leave an unobserved failure.
        task.add_done_callback(finished)
    return await asyncio.shield(task)


async def _closing(gen, client: httpx.AsyncClient):
    try:
        async for block in gen:
            yield block
    finally:
        await client.aclose()


@router.get("/api/preview/{video_id}")
async def preview_track(
    video_id: str, request: Request, purpose: Literal["stream", "offline"] = "stream", sess: dict = Depends(get_current_session)
):
    """Proxy-stream the best audio for a YouTube video without downloading it.

    Fetched upstream in ranged chunks (see services.preview_stream) and served
    with byte-range support so players can seek.
    """
    if not _YT_VIDEO_ID_RE.match(video_id):
        raise HTTPException(status_code=400, detail="invalid video id")
    sources.allowed("youtube", video_id, purpose)
    started = time.perf_counter()
    pid = playback_id()
    song = stream_buffer.get(owner(sess), video_id)
    if song is not None:
        # Already in this user's memory buffer: a seek or replay needs no provider at all.
        response = _buffered(song, request, sess, Observation(pid, "external", media_tag(video_id), "buffer-hit"))
        response.headers['Server-Timing'] = f'resolve;dur=0, probe;dur=0, buffer;desc="hit", id;desc="{pid}"'
        return response
    cached = _stream_info_cache.get(video_id) is not None
    url, headers = await _resolve_stream(video_id)
    resolved = time.perf_counter()
    sources.allowed("youtube", video_id, purpose)
    response = await proxy_audio(url, headers, request, sess, video_id, buffer_for=owner(sess), pid=pid)
    response.headers['Server-Timing'] = (
        f'resolve;dur={(resolved-started)*1000:.1f}, probe;dur={(time.perf_counter()-resolved)*1000:.1f}, '
        f'url_cache;desc="{ "hit" if cached else "miss" }", id;desc="{pid}"')
    return response


def _buffered(song, request: Request, sess: dict, observe: Observation | None = None):
    db.require_active_session(sess)
    wanted = parse_range(request.headers.get("range"))
    resolved = resolve_range(wanted, song.total)
    if resolved is None:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{song.total}"})
    start, end = resolved
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1)}
    if wanted is not None:
        headers["Content-Range"] = f"bytes {start}-{end}/{song.total}"
    if observe:
        observe.start, observe.end = start, end
    return StreamingResponse(guarded(song.read(start, end), sess, observe=observe), status_code=206 if wanted is not None else 200,
                             media_type=song.content_type, headers=headers)


async def _probe(client: httpx.AsyncClient, url: str, headers: dict, video_id: str):
    """Probe the source, following the provider's own redirects between its media hosts.

    The provider often answers a fresh location with a 302 to another of its servers.
    Only an https location on the same media domain is followed (at most three times,
    with the same reduced headers); anything else stays an error.
    """
    for _ in range(4):
        try:
            return url, await probe_upstream(client, url, headers)
        except httpx.HTTPStatusError as exc:
            location = exc.response.headers.get("location")
            if exc.response.status_code not in (301, 302, 303, 307, 308) or not location:
                raise
            if not _YT_VIDEO_ID_RE.match(video_id):
                raise
            try:
                url, headers = _safe_stream(location, headers)
            except HTTPException:
                raise exc from None
            _stream_info_cache.put(video_id, url, headers)
    raise httpx.TooManyRedirects("too many media redirects")


_preparing = {}  # owner -> videos being resolved ahead of playback
PREPARE_TIMEOUT = 90
_prepared_at = {}  # owner -> recent request times


@router.post("/api/preview/{video_id}/prepare", status_code=202)
async def prepare_track(video_id: str, sess: dict = Depends(get_current_session)):
    """Get the next song ready ahead of time so pressing play does not wait for it.

    The stream location is resolved and the song is fetched into this user's memory buffer
    (see services.stream_buffer): nothing is written to disk and it is not a listen. Bounded
    per user (one in flight, twelve per minute, a handful of songs) and globally by the
    shared resolver and the buffer size; a refusal is not an error for playback.
    """
    if not _YT_VIDEO_ID_RE.match(video_id):
        raise HTTPException(status_code=400, detail="invalid video id")
    db.require_active_session(sess)
    sources.allowed("youtube", video_id, "stream")
    user = owner(sess)
    buffered = stream_buffer.get(user, video_id)
    if buffered is not None:
        return {"state": "ready" if buffered.complete else "preparing"}
    now = time.monotonic()
    recent = [t for t in _prepared_at.get(user, []) if now - t < 60]
    if _preparing.get(user) or len(recent) >= 12 or len(_preparing) >= 16:
        _prepared_at[user] = recent
        return {"state": "skipped"}
    _prepared_at[user] = [*recent, now]

    async def work():
        try:
            async with asyncio.timeout(PREPARE_TIMEOUT):
                url, headers = await _resolve_stream(video_id)
                db.require_active_session(sess)
                sources.allowed("youtube", video_id, "stream")
                async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=60.0), follow_redirects=False,
                                             trust_env=False) as client:
                    url, upstream = await _probe(client, url, headers, video_id)
                # A logout or permission change while resolving/probing must not
                # create a new buffer after revocation. No await before start.
                db.require_active_session(sess)
                sources.allowed("youtube", video_id, "stream")
                song = stream_buffer.start(user, video_id, url, headers, upstream.total, upstream.content_type)
                if song is not None and song.task is not None:
                    # Keep the per-user slot until the audio, not just its URL, has
                    # arrived. Giving up (timeout, cancellation) stops the download only
                    # when nobody is listening: the song may already be playing from this
                    # same fill, and abandoning its preparation must not cut it.
                    try:
                        await asyncio.shield(song.task)
                    except BaseException:
                        if not song.readers and not song.task.done():
                            song.task.cancel()
                        raise
        except (HTTPException, httpx.HTTPError, OSError, TimeoutError):
            pass  # Playback will report the failure if the song is actually requested.
        finally:
            if _preparing.get(user) is task:
                del _preparing[user]

    task = asyncio.create_task(work())
    _preparing[user] = task
    return {"state": "preparing"}


async def proxy_audio(url: str, headers: dict, request: Request, sess: dict, video_id: str = "authorized",
                      buffer_for: str | None = None, pid: str | None = None):
    """Shared range-aware transport for existing and explicitly authorized sources."""
    db.require_active_session(sess)
    client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=60.0), follow_redirects=False, trust_env=False)
    try:
        url, upstream = await _probe(client, url, headers, video_id)
    except httpx.HTTPStatusError as exc:
        # A cached URL can go stale (403); forget it so the next attempt re-resolves.
        _stream_info_cache.invalidate(video_id)
        await client.aclose()
        log.warning("preview %s: upstream returned %s", video_id, exc.response.status_code)
        raise HTTPException(status_code=502, detail="couldn't fetch preview") from exc
    except Exception as exc:
        await client.aclose()
        log.warning("preview %s: upstream probe failed (%s)", video_id, type(exc).__name__)
        raise HTTPException(status_code=502, detail="couldn't fetch preview") from exc
    except BaseException:
        await client.aclose()
        raise

    def observation(source):
        return Observation(pid, "external", media_tag(video_id), source) if pid else None

    if upstream.total is None:
        return StreamingResponse(
            guarded(_closing(relay_plain(client, url, headers), client), sess, observe=observation("relay-plain")),
            media_type=upstream.content_type,
        )

    if buffer_for:
        song = stream_buffer.start(buffer_for, video_id, url, headers, upstream.total, upstream.content_type)
        if song is not None:
            await client.aclose()
            return _buffered(song, request, sess, observation("buffer-fill"))
    wanted = parse_range(request.headers.get("range"))
    resolved = resolve_range(wanted, upstream.total)
    if resolved is None:
        await client.aclose()
        return Response(
            status_code=416, headers={"Content-Range": f"bytes */{upstream.total}"}
        )
    start, end = resolved
    response_headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
    }
    status = 200
    if wanted is not None:
        status = 206
        response_headers["Content-Range"] = f"bytes {start}-{end}/{upstream.total}"
    observe = observation("relay")
    if observe:
        observe.start, observe.end = start, end
    return StreamingResponse(
        guarded(_closing(relay_ranged(client, url, headers, start, end), client), sess, observe=observe),
        status_code=status,
        media_type=upstream.content_type,
        headers=response_headers,
    )


@router.delete("/api/track/{track_id}")
async def delete_track(track_id: str, sess: dict = Depends(get_current_session)):
    """Delete only for explicitly granted admins, within their assigned music root."""
    if not sess.get("is_admin") or sess["username"] not in DELETE_USERS:
        raise HTTPException(403, "music deletion is not permitted")
    if not await navidrome_client.is_admin(sess["username"], sess["salt"], sess["token"]):
        raise HTTPException(403, "music deletion is no longer permitted")
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{NAVIDROME_URL}/rest/getSong",
            params={"id": track_id, **auth_params(sess["username"], sess["salt"], sess["token"])},
        )
        r.raise_for_status()
        body = r.json().get("subsonic-response", {})

    if body.get("status") != "ok" or not body.get("song"):
        raise HTTPException(status_code=404, detail="track not found")

    song = body["song"]
    library_id = await navidrome_client.require_library_access(sess)

    # Visibility in Navidrome does not imply permission to remove shared files.
    try:
        root = safe_files.library_root(sess.get("library_path"), MUSIC_DIR)
        with db.active_session(sess):
            file_path = safe_files.unlink_music(root, song.get("path") or "")
    except (ValueError, OSError) as exc:
        raise HTTPException(409, "file unavailable or outside the permitted library") from exc
    target = navidrome_client.scan_target(library_id, str(root), file_path.parent)
    await navidrome_client.scan_until(
        sess["username"], sess["salt"], sess["token"],
        done=lambda: navidrome_client.song_is_unlisted(
            track_id, song.get("title") or "", sess["username"], sess["salt"], sess["token"]),
        targets=[target] if target else None,
    )
    from routes import membership  # Imported here: routes.membership is loaded after this module.
    membership.forget(owner(sess))
    return {"ok": True}


@router.get("/api/external/{source_id}")
async def external(source_id: str, request: Request, purpose: Literal["stream", "offline"] = "stream", sess: dict = Depends(get_current_session)):
    url = sources.audio_url(source_id, purpose)
    record = sources.allowed("authorized_http", source_id, purpose)
    if record.get("cache") is True:
        cached = await audio_cache.get(owner(sess), source_id, url)
        if cached:
            db.require_active_session(sess)
            data, mime = cached
            wanted = parse_range(request.headers.get("range"))
            resolved = resolve_range(wanted, len(data))
            if resolved is None:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{len(data)}"})
            start, end = resolved
            headers = {"Accept-Ranges": "bytes"}
            if wanted:
                headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
            headers["Content-Length"] = str(end - start + 1)
            async def cached_body():
                for offset in range(start, end + 1, 64 * 1024):
                    yield data[offset:min(offset + 64 * 1024, end + 1)]
            return StreamingResponse(guarded(cached_body(), sess), status_code=206 if wanted else 200,
                                     headers=headers, media_type=mime)
    return await proxy_audio(url, {}, request, sess)
