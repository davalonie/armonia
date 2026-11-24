import asyncio
import re
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from db import init_db
from homelab import audio_cache, listening, releases
from homelab import store as music_store
from routes import (
    artist,
    discover,
    download,
    home,
    import_batch,
    import_playlist,
    library,
    manual_inbox,
    membership,
    mixed_playlists,
    oidc,
    playlist_edit,
    search,
    stats,
    stream,
    tracks,
)
from routes import auth as auth_routes
from routes import listening as listening_routes
from routes import sources as source_routes
from services.safe_logging import install as install_safe_logging

install_safe_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    music_store.init()
    releases.init()
    listening.recover()
    task = asyncio.create_task(listening.worker())
    cache_task = asyncio.create_task(audio_cache.worker())
    saver_task = asyncio.create_task(stream._low.worker())
    try:
        yield
    finally:
        saver_task.cancel()
        with suppress(asyncio.CancelledError):
            await saver_task
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        cache_task.cancel()
        with suppress(asyncio.CancelledError):
            await cache_task


app = FastAPI(title="Music Homelab", lifespan=lifespan)


@app.exception_handler(httpx.HTTPError)
async def upstream_error(request: Request, exc: httpx.HTTPError):
    return JSONResponse(status_code=502, content={"detail": "music service unavailable"})



class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/") and any(path.endswith(ext) for ext in (".js", ".css", ".html")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


# Content-Security-Policy tuned for the built SPA: external ESM only (no inline
# scripts), Google Fonts, and remote thumbnail images from search results. Audio
# is proxied same-origin through /api/stream, so media-src stays 'self'.
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' ; "
    "font-src 'self' ; "
    "img-src 'self' data: https:; "
    "media-src 'self' blob:; "
    # The only cross-origin requests: the owner's own Spotify sign-in for «Importar todo».
    "connect-src 'self' https://accounts.spotify.com https://api.spotify.com; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "object-src 'none'"
)


# Navidrome names an album's or artist's cover after when it last changed ("al-<id>_<hex>"), so under one name
# it never changes: the phone keeps it for good. A song's cover ("mf-<id>", measured in Navidrome 0.64.2) keeps
# its name when it changes: the phone keeps it a week, then asks with its ETag and gets 304 while it is the same
# (routes/library.py). Before 0.5.3 every cover said no-store, and the phone, which honours it, kept none on disk.
_VERSIONED_COVER = re.compile(r"^[a-z]{2}-[A-Za-z0-9]+_[0-9a-f]+$")


_RELEASE_COVER = re.compile(r"^/api/home/releases/[0-9a-f-]{36}/cover$")


def _cacheable_cover(request: Request, response) -> bool:
    image = response.status_code == 200 and response.headers.get("content-type", "").startswith("image/")
    if _RELEASE_COVER.match(request.url.path) and image:
        # A release's cover does not change. With no-store the phone kept none on disk and fetched them again
        # after every restart of the app; now it keeps them a week, like a song's cover.
        response.headers["Cache-Control"] = "private, max-age=604800"
        return True
    if request.url.path not in ("/api/library/getCoverArt", "/api/library/getCoverArt.view"):
        return False
    if not image and response.status_code != 304:
        return False
    if request.query_params.get("id", "").startswith("armonia-art-"):
        return False  # Recheck access after a private playlist is deleted or unshared.
    versioned = _VERSIONED_COVER.match(request.query_params.get("id", ""))
    response.headers["Cache-Control"] = "private, max-age=31536000, immutable" if versioned else "private, max-age=604800"
    return True


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", _CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        # no-referrer stops the ?session= token leaking via the Referer header.
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/") and not _cacheable_cover(request, response):
            response.headers["Cache-Control"] = "private, no-store"
        return response


app.add_middleware(NoCacheStaticMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(auth_routes.router)
app.include_router(oidc.router)
app.include_router(mixed_playlists.router)
app.include_router(discover.router)
app.include_router(home.router)
app.include_router(listening_routes.router)
app.include_router(source_routes.router)
app.include_router(search.router)
app.include_router(artist.router)
app.include_router(download.router)
app.include_router(library.router)
app.include_router(stream.router)
app.include_router(tracks.router)
app.include_router(stats.router)
app.include_router(import_playlist.router)
app.include_router(import_batch.router)
app.include_router(manual_inbox.router)
app.include_router(playlist_edit.router)
app.include_router(membership.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Static SPA last so /api/* and /health win the route table.
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
