import asyncio
import contextlib
import os
import re
import shutil
import tempfile
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from pathlib import Path
from threading import Lock, get_ident
from typing import Any

from anyio import from_thread, to_thread

# YouTube extraction (search previews + downloads) needs a JavaScript runtime to
# solve the player-signature / "nsig" challenge. The Docker image ships the Deno
# binary on PATH, which yt-dlp auto-detects and uses — no per-call option needed.
# If a future yt-dlp requires explicit selection, set it via the shared opts, e.g.
#   "extractor_args": {"youtube": {"jsi": ["Deno"]}}


class DownloadCancelled(Exception):
    pass

from yt_dlp import YoutubeDL

from config import MUSIC_DIR, YTDLP_COOKIES_FILE
from homelab import operations, publications
from services import import_metrics, safe_files, tagger_service


def describe_error(exc: Exception) -> str:
    """Condense a yt-dlp / download exception into one short, human-readable reason.

    Keeps backend logs and the UI free of giant tracebacks while still telling
    you *why* a track failed.
    """
    msg = str(exc)
    low = msg.lower()
    if any(s in low for s in ("confirm your age", "verify your age", "inappropriate for some", "sure you're an adult")):
        return "age-restricted (needs an age-verified account cookie)"
    if "not a bot" in low:
        return "bot check (needs cookies)"
    if "http error 403" in low or "forbidden" in low:
        return "blocked by YouTube (HTTP 403 — often transient, retry later)"
    if "private video" in low:
        return "private video"
    # Check the format-specific phrasing before the generic "is not available"
    # below, since "requested format is not available" contains that substring.
    if any(s in low for s in ("requested format is not available", "no video formats", "no audio")):
        return "no downloadable audio format"
    if any(s in low for s in ("video unavailable", "is not available", "no longer available", "has been removed")):
        return "video unavailable"
    if "sign in" in low:
        return "requires sign-in (needs cookies)"
    if "timed out" in low or "timeout" in low:
        return "network timeout"
    # Provider errors can contain signed URLs, cookies or local paths.
    return "download failed; source unavailable or unsupported"


def is_retryable(exc: Exception) -> bool:
    """True for transient failures worth a second attempt — not permanent blocks.

    Age-restricted / private / unavailable / sign-in won't change on retry, so we
    skip those; 403s, timeouts and signature blips often succeed the second time.
    """
    low = str(exc).lower()
    permanent = (
        "confirm your age", "verify your age", "inappropriate for some", "sure you're an adult",
        "private video", "video unavailable", "is not available", "no longer available",
        "has been removed", "sign in", "not a bot", "members-only",
        "requested format is not available",
    )
    if any(s in low for s in permanent):
        return False
    transient = (
        "http error 403", "forbidden", "timed out", "timeout", "unable to download video data",
        "unable to extract", "nsig", "signature", "fragment", "connection", "temporarily",
        "read timed out", "503", "500",
    )
    return any(s in low for s in transient)


@contextlib.contextmanager
def _cookiefile():
    """Yield a throwaway, writable copy of the cookies file (or None).

    yt-dlp rewrites the cookiefile on close. Handing it a per-call temp copy keeps
    the real file (often a read-only mount) untouched and stops two concurrent
    downloads from clobbering the same file. The temp is removed afterwards.
    """
    if not YTDLP_COOKIES_FILE:
        yield None
        return
    src = Path(YTDLP_COOKIES_FILE)
    if not (src.is_file() and src.stat().st_size > 0):
        yield None
        return
    fd, tmp = tempfile.mkstemp(prefix="armonia_cookies_", suffix=".txt")
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        yield tmp
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


@contextlib.contextmanager
def _ytdl(opts: dict):
    """A YoutubeDL context with a throwaway cookie copy attached (see _cookiefile)."""
    with _cookiefile() as cf:
        if cf:
            opts = {**opts, "cookiefile": cf}
        with YoutubeDL(opts) as ydl:
            yield ydl


_INVALID_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize(s: str) -> str:
    s = _INVALID_FS_CHARS.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Strip leading/trailing dots so a value like ".." can't become a path
    # component that escapes the target directory (path traversal).
    s = s.strip(".")
    return s[:100] or "Unknown"


def search(query: str, limit: int = 10, source: str = "youtube_music") -> list[dict[str, Any]]:
    if source == "youtube_music":
        return _search_ytmusic(query, limit)
    return _search_youtube(query, limit)


_search_scope = ContextVar('public_search_connections', default=None)


@contextlib.contextmanager
def search_connection_scope():
    """Anonymous provider connections confined to one operation, one per thread."""
    clients = {}
    token = _search_scope.set(clients)
    try:
        yield
    finally:
        _search_scope.reset(token)
        for _, session in clients.values():
            session.close()


def _music_search_client():
    from ytmusicapi import YTMusic
    clients = _search_scope.get()
    if clients is None:
        return YTMusic()
    key = get_ident()
    if key not in clients:
        import requests
        session = requests.Session()
        request = session.request
        def timed_request(*args, **kwargs):
            kwargs.setdefault('timeout', 30)
            with import_metrics.measure('search_provider_http'):
                return request(*args, **kwargs)
        session.request = timed_request
        clients[key] = YTMusic(requests_session=session), session
    return clients[key][0]


def _search_ytmusic(query: str, limit: int) -> list[dict[str, Any]]:
    ytm = _music_search_client()

    def _normalise(entries: list) -> list[dict[str, Any]]:
        out = []
        for r in entries:
            video_id = r.get("videoId")
            if not video_id:
                continue
            artists = r.get("artists") or []
            artist = ", ".join(a["name"] for a in artists if a.get("name")) or \
                     r.get("author") or r.get("channel") or "Unknown"
            thumbs = r.get("thumbnails") or []
            thumbnail = thumbs[-1]["url"] if thumbs else None
            out.append({
                "videoId": video_id,
                "title": r.get("title") or "Unknown",
                "channel": artist,
                "duration": r.get("duration_seconds") or 0,
                "thumbnail": thumbnail,
                "album": (r.get("album") or {}).get("name") or "",
            })
            if len(out) >= limit:
                break
        return out

    results = ytm.search(query, filter="songs", limit=limit)
    out = _normalise(results)
    if not out:
        # Some content is categorised as "videos" on YT Music rather than "songs"
        results = ytm.search(query, filter="videos", limit=limit)
        out = _normalise(results)
    return out


def _search_youtube(query: str, limit: int) -> list[dict[str, Any]]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noconfig": True,
        "extract_flat": True,
        "skip_download": True,
    }
    with _ytdl(opts) as ydl:
        result = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    entries = (result or {}).get("entries") or []
    out = []
    for e in entries:
        if not e:
            continue
        thumbs = e.get("thumbnails")
        thumbnail = thumbs[-1].get("url") if isinstance(thumbs, list) and thumbs else e.get("thumbnail")
        out.append({
            "videoId": e.get("id"),
            "title": e.get("title") or "Unknown",
            "channel": e.get("channel") or e.get("uploader") or "Unknown",
            "duration": e.get("duration") or 0,
            "thumbnail": thumbnail,
        })
    return out[:limit]


def search_artists(query: str, limit: int = 10) -> list[dict[str, Any]]:
    from ytmusicapi import YTMusic
    ytm = YTMusic()

    def _normalise(entries: list) -> list[dict[str, Any]]:
        out = []
        for r in entries:
            result_type = r.get("resultType") or ""
            # In unfiltered results skip non-artists; in filtered results resultType is absent
            if result_type and result_type != "artist":
                continue
            channel_id = r.get("browseId") or ""
            if not channel_id:
                continue
            thumbs = r.get("thumbnails") or []
            out.append({
                "channelId": channel_id,
                "name": r.get("artist") or r.get("name") or "Unknown",
                "thumbnail": thumbs[-1]["url"] if thumbs else None,
                "subscribers": r.get("subscribers") or "",
            })
            if len(out) >= limit:
                break
        return out

    out = _normalise(ytm.search(query, filter="artists", limit=limit))
    if not out:
        out = _normalise(ytm.search(query, limit=limit))
    return out


def get_artist(channel_id: str) -> dict[str, Any]:
    from ytmusicapi import YTMusic
    ytm = YTMusic()
    data = ytm.get_artist(channel_id)
    thumbs = data.get("thumbnails") or []

    def _norm_song(s: dict) -> dict:
        artists = s.get("artists") or []
        artist = ", ".join(a["name"] for a in artists if a.get("name")) or "Unknown"
        album_obj = s.get("album") or {}
        t = s.get("thumbnails") or []
        return {
            "videoId": s.get("videoId"),
            "title": s.get("title") or "Unknown",
            "artist": artist,
            "album": album_obj.get("name") or "",
            "duration": s.get("duration_seconds") or 0,
            "thumbnail": t[-1]["url"] if t else None,
        }

    def _norm_release(r: dict) -> dict:
        t = r.get("thumbnails") or []
        return {
            "browseId": r.get("browseId"),
            "title": r.get("title") or "Unknown",
            "year": r.get("year") or "",
            "type": r.get("type") or "Album",
            "thumbnail": t[-1]["url"] if t else None,
        }

    def _fetch_full_releases(section: dict) -> list[dict]:
        """get_artist returns a preview; use get_artist_albums with params for the full list."""
        params = section.get("params")
        if params:
            try:
                return ytm.get_artist_albums(channel_id, params, limit=100) or []
            except Exception:
                pass
        return section.get("results") or []

    top_songs_raw = (data.get("songs") or {}).get("results") or []
    albums_raw = _fetch_full_releases(data.get("albums") or {})
    singles_raw = _fetch_full_releases(data.get("singles") or {})

    return {
        "channelId": channel_id,
        "name": data.get("name") or "Unknown",
        "description": data.get("description") or "",
        "thumbnail": thumbs[-1]["url"] if thumbs else None,
        "topSongs": [_norm_song(s) for s in top_songs_raw if s.get("videoId")],
        "albums": [_norm_release(r) for r in albums_raw if r.get("browseId")],
        "singles": [_norm_release(r) for r in singles_raw if r.get("browseId")],
    }


def get_artist_songs(channel_id: str) -> list[dict[str, Any]]:
    """All songs by an artist via the songs playlist (get_artist only returns top 5)."""
    from ytmusicapi import YTMusic
    ytm = YTMusic()
    artist = ytm.get_artist(channel_id)
    songs_obj = artist.get("songs") or {}
    browse_id = songs_obj.get("browseId")

    if not browse_id:
        results = songs_obj.get("results") or []
    else:
        playlist = ytm.get_playlist(browse_id, limit=200)
        results = playlist.get("tracks") or []

    out = []
    for s in results:
        if not s.get("videoId"):
            continue
        artists = s.get("artists") or []
        artist_name = ", ".join(a["name"] for a in artists if a.get("name")) or "Unknown"
        album_obj = s.get("album") or {}
        t = s.get("thumbnails") or []
        out.append({
            "videoId": s["videoId"],
            "title": s.get("title") or "Unknown",
            "artist": artist_name,
            "album": album_obj.get("name") or "",
            "duration": s.get("duration_seconds") or 0,
            "thumbnail": t[-1]["url"] if t else None,
        })
    return out


def get_album(browse_id: str) -> dict[str, Any]:
    from ytmusicapi import YTMusic
    data = YTMusic().get_album(browse_id)
    thumbs = data.get("thumbnails") or []
    artists = data.get("artists") or []
    artist = ", ".join(a["name"] for a in artists if a.get("name")) or "Unknown"

    tracks = []
    for t in (data.get("tracks") or []):
        if not t.get("videoId"):
            continue
        track_artists = t.get("artists") or []
        track_artist = ", ".join(a["name"] for a in track_artists if a.get("name")) or artist
        tracks.append({
            "videoId": t["videoId"],
            "title": t.get("title") or "Unknown",
            "artist": track_artist,
            "trackNumber": t.get("trackNumber") or 0,
            "duration": t.get("duration_seconds") or 0,
        })

    return {
        "browseId": browse_id,
        "title": data.get("title") or "Unknown",
        "artist": artist,
        "year": data.get("year") or "",
        "type": data.get("type") or "Album",
        "thumbnail": thumbs[-1]["url"] if thumbs else None,
        "tracks": tracks,
    }


class _StreamResolver:
    """One long-lived extractor for stream locations.

    A fresh YoutubeDL per song repeats the provider's start-up work (player and client
    setup) every time: measured about 1.7 s per song against about 0.9 s when the same
    instance resolves the next one. The instance is used by one thread at a time, is
    replaced after a failure or after REUSE_SECONDS (so refreshed cookies are picked up),
    and keeps its private cookie copy for exactly as long as it lives.
    """

    REUSE_SECONDS = 20 * 60
    OPTS = {"quiet": True, "no_warnings": True, "noconfig": True,
            "format": "bestaudio[ext=m4a]/bestaudio", "noplaylist": True}

    def __init__(self):
        self._lock = Lock()
        self._stack = None
        self._ydl = None
        self._born = 0.0

    def _close(self):
        stack, self._stack, self._ydl = self._stack, None, None
        if stack is not None:
            with contextlib.suppress(Exception):
                stack.close()

    def _instance(self):
        if self._ydl is None or time.monotonic() - self._born > self.REUSE_SECONDS:
            self._close()
            stack = contextlib.ExitStack()
            try:
                self._ydl = stack.enter_context(_ytdl(dict(self.OPTS)))
            except BaseException:
                stack.close()
                raise
            self._stack, self._born = stack, time.monotonic()
        return self._ydl

    def resolve(self, video_id: str):
        with self._lock:
            try:
                return self._instance().extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            except BaseException:
                self._close()  # Never reuse an instance that just failed.
                raise


_stream_resolver = _StreamResolver()


def get_stream_info(video_id: str) -> tuple[str, dict]:
    """Return (url, http_headers) for the best audio stream — no download."""
    info = _stream_resolver.resolve(video_id)
    if not info:
        raise RuntimeError("yt-dlp returned no info")
    # Prefer the selected format's URL
    formats = info.get("requested_formats") or [info]
    fmt = formats[0]
    return fmt["url"], fmt.get("http_headers", {})


def _download_staged(video_id: str, artist: str, title: str, source: str = "youtube",
             cancel_check: Callable[[], bool] | None = None,
             music_dir: str | None = None) -> str:
    """Download bestaudio in its native container. Returns the absolute file path.

    `music_dir` overrides the default MUSIC_DIR — used to route a user's
    download into their own Navidrome library path.
    """
    base = music_dir or MUSIC_DIR
    artist_dir = Path(base)

    filename_stem = _sanitize(f"{artist} - {title}")
    outtmpl = str(artist_dir / f"{filename_stem}.%(ext)s")
    maximum = min(64 * 1024**2, int(os.environ.get("MUSIC_DOWNLOAD_MAX_BYTES", str(64 * 1024**2))))
    started = time.monotonic()

    stage_started = time.monotonic()
    current_stage = 'audio_resolution'
    def transition(name):
        nonlocal stage_started, current_stage
        now = time.monotonic()
        if current_stage != name:
            import_metrics.event(current_stage, now - stage_started)
            stage_started, current_stage = now, name
            import_metrics.event(name, 0)
    def postprocess(d):
        transition('processing')
    def _progress_hook(d):
        transition('download' if d.get('status') != 'finished' else 'processing')
        if d.get("downloaded_bytes", 0) > maximum or time.monotonic() - started > 180:
            raise RuntimeError("download size or time limit reached")
        if cancel_check and cancel_check():
            raise DownloadCancelled("cancelled by user")

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noconfig": True,   # ignore any yt-dlp.conf that could override outtmpl
        # Prefer m4a (AAC) since it tags cleanly and is universally supported.
        # Fall back to bestaudio (usually opus-in-webm) and remux below.
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "max_filesize": maximum,
        "concurrent_fragment_downloads": 1,
        # preferredcodec="best" keeps the source codec (no re-encode) and only
        # remuxes the container when needed — e.g. opus-in-webm → opus-in-ogg.
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "best",
            },
            # Embed the YouTube thumbnail into the audio file so Navidrome
            # can display cover art without a separate image fetch.
            {
                "key": "EmbedThumbnail",
            },
        ],
        "writethumbnail": True,
        "progress_hooks": [_progress_hook],
        "postprocessor_hooks": [postprocess],
        # Fail a stalled connection instead of hanging forever (which would wedge
        # an import slot). yt-dlp also retries fragments a few times on its own.
        "socket_timeout": 30,
        "retries": 2,
        "fragment_retries": 2,
    }

    if source == "youtube_music":
        url = f"https://music.youtube.com/watch?v={video_id}"
    else:
        url = f"https://www.youtube.com/watch?v={video_id}"

    with _ytdl(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        finally:
            import_metrics.event(current_stage, time.monotonic() - stage_started)
        if not info:
            raise RuntimeError("yt-dlp returned no info")

        requested = info.get("requested_downloads") or []
        if requested and requested[0].get("filepath"):
            return requested[0]["filepath"]
        return ydl.prepare_filename(info)


def download(video_id: str, artist: str, title: str, source: str = "youtube",
             cancel_check: Callable[[], bool] | None = None,
             music_dir: str | None = None, album: str = "Singles",
             before_publish: Callable[[], object] | None = None,
             final_guard=contextlib.nullcontext, record_intent=None,
             artists=None, album_artist: str | None = None, details=None) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("invalid video id")
    root = safe_files.library_root(music_dir, MUSIC_DIR)
    with safe_files.directory(root):
        pass
    # yt-dlp, ffmpeg and mutagen operate only in this private temporary directory.
    with tempfile.TemporaryDirectory(prefix="music-import-") as staging:
        path = Path(_download_staged(video_id, artist, title, source, cancel_check, staging))
        safe_files.relative_file(Path(staging), str(path))
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in tagger_service.AUDIO_EXTENSIONS:
            raise ValueError("invalid downloaded file")
        size = path.stat().st_size
        reserve = int(os.environ.get("MUSIC_FREE_SPACE_RESERVE_BYTES", str(1024**3)))
        if size > 96 * 1024**2 or shutil.disk_usage(root).free < reserve + size:
            raise ValueError("library storage limit reached")
        with import_metrics.measure("processing"):
            tagger_service.tag(str(path), artist, title, album.strip() or "Singles", artists, album_artist, details)
        if cancel_check and cancel_check():
            raise DownloadCancelled("cancelled by user")
        if before_publish:
            before_publish()
        with import_metrics.measure("publication"):
            return safe_files.publish(path, root, _sanitize(artist), _sanitize(f"{artist} - {title}"), final_guard=final_guard, record_intent=record_intent)


# Global ceiling on concurrent track downloads, shared across single downloads
# and playlist imports. Too many at once trips YouTube rate-limiting (403s) and
# spikes CPU on remux; this caps the total regardless of how many requests or
# imports are in flight.
MAX_CONCURRENT_DOWNLOADS = 3
_download_sem = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)


async def download_limited(
    video_id: str, artist: str, title: str, source: str = "youtube",
    *, cancel_check: Callable[[], bool] | None = None, music_dir: str | None = None, album: str = "Singles",
    authorize: Callable[[], Awaitable[object]],
    final_guard=contextlib.nullcontext,
    record_intent=None,
    allow_repeat=False,
    artists=None,
    album_artist: str | None = None,
    details=None,
) -> str:
    """Async wrapper around download(): runs it in a worker thread, gated by the
    shared download semaphore so concurrency stays bounded process-wide."""
    root = safe_files.library_root(music_dir, MUSIC_DIR)
    source_key = "youtube:" + video_id
    def persist(path):
        publications.record(root, source_key, path)
        if record_intent:
            record_intent(path)
    with operations.reserve(str(root), source_key):
        async with _download_sem:
            await authorize()
            if not allow_repeat:
                publications.require_unpublished(root, source_key)
            return await to_thread.run_sync(
                lambda: download(
                    video_id, artist, title, source,
                    cancel_check=cancel_check, music_dir=music_dir, album=album,
                    before_publish=lambda: from_thread.run(authorize),
                    final_guard=final_guard,
                    record_intent=persist,
                    artists=artists,
                    album_artist=album_artist,
                    details=details,
                )
            )
