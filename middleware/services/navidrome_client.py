import asyncio
import hashlib
import logging
import re
import secrets
import time
import unicodedata
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

import db
from config import NAVIDROME_URL

log = logging.getLogger(__name__)


# One pool per operation, never shared across users or retained credentials.
_client_scope = ContextVar("navidrome_client", default=None)


@asynccontextmanager
async def connection_scope():
    async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
        token = _client_scope.set(client)
        try:
            yield
        finally:
            _client_scope.reset(token)


@asynccontextmanager
async def _client(**kwargs):
    current = _client_scope.get()
    if current is not None:
        yield current
    else:
        async with httpx.AsyncClient(**kwargs) as client:
            yield client


def normalize(s: str) -> str:
    """Loose comparison key for titles and artists (case, accents, punctuation)."""
    return _norm(s)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())

CLIENT_ID = "armonia"
API_VERSION = "1.16.1"


def make_credentials(password: str) -> tuple[str, str]:
    """Derive a reusable Subsonic (salt, token) pair from a password.

    Subsonic auth is token = md5(password + salt) with a client-chosen salt that
    may be reused across requests. We compute this once at login and persist only
    the (salt, token) — never the cleartext password. The token is replayable
    against the Subsonic API but, unlike the password, can't be used for
    Navidrome's web login or reused on other services.
    """
    salt = secrets.token_hex(16)
    token = hashlib.md5((password + salt).encode()).hexdigest()
    return salt, token


def auth_params(username: str, salt: str, token: str) -> dict[str, str]:
    """Subsonic auth params from a stored (salt, token) pair."""
    return {
        "u": username,
        "t": token,
        "s": salt,
        "v": API_VERSION,
        "c": CLIENT_ID,
        "f": "json",
    }


async def ping(username: str, salt: str, token: str) -> dict[str, Any]:
    async with _client(timeout=10) as client:
        r = await client.get(
            f"{NAVIDROME_URL}/rest/ping",
            params=auth_params(username, salt, token),
        )
        r.raise_for_status()
        return r.json().get("subsonic-response", {})


async def is_admin(username: str, salt: str, token: str) -> bool:
    """Whether the user has the Navidrome admin role.

    A user may always query their own record via Subsonic `getUser`, which
    carries `adminRole`. Returns False on any error so a lookup failure never
    grants elevated visibility.
    """
    try:
        async with _client(timeout=10) as client:
            r = await client.get(
                f"{NAVIDROME_URL}/rest/getUser",
                params={"username": username, **auth_params(username, salt, token)},
            )
            r.raise_for_status()
        body = r.json().get("subsonic-response", {})
        if body.get("status") != "ok":
            return False
        return bool(body.get("user", {}).get("adminRole"))
    except Exception:
        return False


async def start_scan(
    username: str, salt: str, token: str, targets: list[str] | None = None,
) -> dict[str, Any]:
    """Start a Navidrome scan. `targets` (Navidrome >= 0.59) limits it to folders,
    each as `<libraryId>:<path relative to the library root>`; omit for a full scan."""
    params = list(auth_params(username, salt, token).items())
    params += [("target", t) for t in targets or []]
    async with _client(timeout=30) as client:
        r = await client.get(f"{NAVIDROME_URL}/rest/startScan", params=params)
        r.raise_for_status()
        return r.json()


def scan_target(library_id: int | None, library_root: str | None, folder: str | Path) -> str | None:
    """`<libraryId>:<relative folder>` for a targeted scan of `folder`, or None when
    it can't be expressed (unknown library, folder outside or equal to the root),
    in which case callers fall back to a full scan.

    A folder that no longer exists is replaced by its nearest existing ancestor:
    Navidrome skips a missing target ("Target folder does not exist") without
    dropping the tracks that were in it, so after deleting an artist's last song
    the scan has to cover the folder that contained the removed one."""
    if library_id is None or not library_root:
        return None
    root = Path(library_root).resolve()
    target = Path(folder).resolve()
    while target != root and not target.exists():
        target = target.parent
    try:
        rel = target.relative_to(root)
    except ValueError:
        return None
    if str(rel) in ("", "."):
        return None
    return f"{library_id}:{rel.as_posix()}"


# username -> library id, for sessions created before ids were stored.
_library_id_cache: dict[str, int] = {}


async def require_library_access(sess: dict) -> int:
    """Revalidate a session's write grant. Cached login data is not authority.

    Subsonic exposes current library IDs but not their filesystem paths. An
    administrator changing the path of an existing ID must stop writers and
    revoke sessions before moving/reassigning that directory.
    """
    if not sess.get("library_path") or sess.get("library_id") is None:
        raise HTTPException(403, "assigned library required; sign in again")
    db.require_active_session(sess)
    try:
        library_id = int(sess["library_id"])
        async with _client(timeout=10, trust_env=False, follow_redirects=False) as client:
            r = await client.get(
                f"{NAVIDROME_URL}/rest/getMusicFolders",
                params=auth_params(sess["username"], sess["salt"], sess["token"]),
            )
            r.raise_for_status()
        body = r.json()["subsonic-response"]
        if body.get("status") != "ok":
            raise HTTPException(403, "library access is no longer permitted")
        folders = body.get("musicFolders", {}).get("musicFolder", [])
        accessible = {int(folder["id"]) for folder in folders}
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, "cannot verify current library access") from exc
    if library_id not in accessible:
        raise HTTPException(403, "library access is no longer permitted")
    db.require_active_session(sess)
    return library_id


async def resolve_library_id(sess: dict) -> int | None:
    """The session's Navidrome library id. Older sessions didn't record it; for
    those, a user with exactly one music folder unambiguously owns that id."""
    if sess.get("library_id") is not None:
        return int(sess["library_id"])
    username = sess["username"]
    if username in _library_id_cache:
        return _library_id_cache[username]
    try:
        async with _client(timeout=10) as client:
            r = await client.get(
                f"{NAVIDROME_URL}/rest/getMusicFolders",
                params=auth_params(username, sess["salt"], sess["token"]),
            )
            r.raise_for_status()
            folders = (
                r.json().get("subsonic-response", {}).get("musicFolders", {}).get("musicFolder", [])
            )
    except Exception:
        return None
    if len(folders) != 1:
        return None
    _library_id_cache[username] = int(folders[0]["id"])
    return _library_id_cache[username]


async def _search_songs_strict(query: str, username: str, salt: str, token: str, count: int = 50) -> list[dict]:
    """Like search_songs, but raises on failure instead of returning [] — for
    checks where "no results" must not be confused with "Navidrome errored"."""
    async with _client(timeout=10) as client:
        r = await client.get(
            f"{NAVIDROME_URL}/rest/search3",
            params={"query": query, "songCount": count, "artistCount": 0, "albumCount": 0,
                    **auth_params(username, salt, token)},
        )
        r.raise_for_status()
    body = r.json().get("subsonic-response", {})
    if body.get("status") != "ok":
        raise RuntimeError(f"search3 failed: {body.get('error')}")
    return body.get("searchResult3", {}).get("song") or []


async def song_is_unlisted(track_id: str, title: str, username: str, salt: str, token: str) -> bool:
    """True once the track no longer shows up in the library.

    Not `getSong`: Navidrome keeps a deleted file's track as "missing" (purged
    later by an admin), so lookups by id keep succeeding even though every listing
    — search, artists, albums — has already dropped it."""
    songs = await _search_songs_strict(title, username, salt, token)
    return all(s.get("id") != track_id for s in songs)


async def matching_song_ids(artist: str, title: str, username: str, salt: str, token: str) -> set[str]:
    """Ids of library songs whose (normalised) artist and title match.

    Matching is on tags, not paths: the `path` Navidrome reports is built from the
    tags (Artist/Album/Title.ext), not the file's real location."""
    want_artist, want_title = _norm(artist), _norm(title)
    songs = await search_songs(title, username, salt, token, count=50)
    return {
        s["id"] for s in songs
        if _norm(s.get("title") or "") == want_title and _norm(s.get("artist") or "") == want_artist
    }


async def new_song_visible(
    artist: str, title: str, known_ids: set[str], username: str, salt: str, token: str,
) -> bool:
    """True once a song matching artist/title, and not among `known_ids` (what
    matched before the download), is searchable."""
    return bool(await matching_song_ids(artist, title, username, salt, token) - known_ids)


async def scan_until(
    username: str,
    salt: str,
    token: str,
    done: Callable[[], Awaitable[bool]],
    targets: list[str] | None = None,
    timeout_s: float = 20.0,
    poll_s: float = 0.4,
    targeted_grace_s: float = 6.0,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Scan (targeted when possible) and wait until `done()` reports the change is
    visible, instead of sleeping a fixed time and hoping. If a targeted scan hasn't
    made it visible within `targeted_grace_s`, fall back to one full scan. Returns
    whether the change became visible before `timeout_s`; scan errors are swallowed
    because a slow library refresh must never fail the download or delete."""
    start = clock()
    try:
        await start_scan(username, salt, token, targets)
    except Exception as e:
        log.warning("startScan failed (%s)", type(e).__name__)
    fell_back = not targets
    check_failed = False
    while clock() - start < timeout_s:
        try:
            if await done():
                log.info("library change visible after %.1fs (targets=%s)", clock() - start, targets)
                return True
        except Exception as e:
            if not check_failed:  # once, so a persistent failure doesn't flood the log
                check_failed = True
                log.warning("library visibility check failed (%s)", type(e).__name__)
        if not fell_back and clock() - start >= targeted_grace_s:
            fell_back = True
            log.info("targeted scan not visible after %.1fs, running a full scan", targeted_grace_s)
            try:
                await start_scan(username, salt, token)
            except Exception:
                pass
        await asyncio.sleep(poll_s)
    log.warning("library change still not visible after %.0fs (targets=%s)", timeout_s, targets)
    return False


async def get_user_context(username: str, password: str) -> dict[str, Any]:
    """Native identity and assigned libraries; errors never grant a fallback library."""
    try:
        async with _client(timeout=10) as client:
            login = await client.post(
                f"{NAVIDROME_URL}/auth/login",
                json={"username": username, "password": password},
            )
            login.raise_for_status()
            login_data = login.json() or {}
            token = login_data.get("token")
            user_id = login_data.get("id")
            if not token or not user_id:
                return {"id": None, "libraries": []}

            user_resp = await client.get(
                f"{NAVIDROME_URL}/api/user/{user_id}",
                headers={"x-nd-authorization": f"Bearer {token}"},
            )
            user_resp.raise_for_status()
            libraries = (user_resp.json() or {}).get("libraries") or []

            return {"id": str(user_id), "libraries": [
                {"id": lib.get("id"), "name": lib.get("name") or "", "path": lib.get("path") or ""}
                for lib in libraries
                if lib.get("path")
            ]}
    except Exception:
        return {"id": None, "libraries": []}


async def get_user_libraries(username: str, password: str) -> list[dict[str, Any]]:
    return (await get_user_context(username, password))["libraries"]


async def search_songs(query: str, username: str, salt: str, token: str, count: int = 10) -> list[dict]:
    """Search Navidrome for songs matching `query`. Returns a list of song dicts."""
    try:
        async with _client(timeout=10) as client:
            r = await client.get(
                f"{NAVIDROME_URL}/rest/search3",
                params={
                    "query": query,
                    "songCount": count,
                    "artistCount": 0,
                    "albumCount": 0,
                    **auth_params(username, salt, token),
                },
            )
            r.raise_for_status()
        body = r.json().get("subsonic-response", {})
        if body.get("status") != "ok":
            return []
        return body.get("searchResult3", {}).get("song") or []
    except Exception:
        return []


def _real_duration(reported, wanted):
    """The library reports whole seconds, cut off: 116 means anywhere in [116, 117).

    Comparing that number as if it were exact rejected the import's own download when
    the true difference was inside the tolerance (119.05 s wanted, file of 116.5 s,
    reported as 116: 3.05 s apparent, 2.55 s real). Use the instant of that second
    nearest to the wanted length; a fractional report is taken as it is.
    """
    if not reported:
        return None
    if not wanted or reported != int(reported):
        return reported
    return min(max(wanted, reported), reported + 0.999)


async def find_song_id(artist: str, title: str, username: str, salt: str, token: str, wanted: dict | None = None) -> str | None:
    """Return the Navidrome song id whose artist+title match (normalised), or None."""
    songs = await (_search_songs_strict(title, username, salt, token)
                   if _client_scope.get() is not None else search_songs(title, username, salt, token))
    if wanted is not None:
        from homelab import matcher
        from homelab.models import Track
        candidates = [Track(source="navidrome", source_id=s["id"], title=s.get("title") or "Unknown",
                            artist=s.get("artist") or "Unknown", album=s.get("album") or "",
                            duration=_real_duration(s.get("duration"), wanted.get("duration"))) for s in songs]
        selected = matcher.rank(wanted, candidates)["selected"]
        return selected["source_id"] if selected else None
    na, nt = _norm(artist), _norm(title)
    matches = [s.get("id") for s in songs if _norm(s.get("title", "")) == nt and _norm(s.get("artist", "")) == na]
    return matches[0] if len(matches) == 1 else None


async def create_playlist(name: str, song_ids: list[str], username: str, salt: str, token: str) -> str | None:
    """Create a playlist with the given songs. Returns the new playlist id, or None."""
    try:
        # Songs go in a form body, as import_playlist_request does: thousands of ids in
        # the address could exceed what a server or proxy accepts.
        pairs = [("name", name)] + [("songId", sid) for sid in song_ids]
        async with _client(timeout=60) as client:
            r = await client.post(
                f"{NAVIDROME_URL}/rest/createPlaylist",
                params=list(auth_params(username, salt, token).items()),
                content=urlencode(pairs),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
        body = r.json().get("subsonic-response", {})
        if body.get("status") != "ok":
            return None
        return (body.get("playlist") or {}).get("id")
    except Exception:
        return None


async def trigger_scan_and_wait(username: str, salt: str, token: str, scan_wait_s: float = 1.5) -> None:
    """Trigger a Navidrome scan and give it long enough to finish.

    We deliberately don't poll getScanStatus to detect completion: its
    `lastScan` field only updates on full scans (not the quick-selective
    scans incremental additions use), and `scanning: false` flips back too
    fast (~30ms) to reliably catch. A short fixed wait covers Navidrome's
    on-demand scan in 99% of cases; if a download is somehow still missing,
    re-entering the Library tab re-fetches `getArtists` anyway."""
    try:
        await start_scan(username, salt, token)
    except Exception:
        return
    await asyncio.sleep(scan_wait_s)


async def subsonic_request(verb, session, pairs):
    """Strict playlist operations: an upstream failure is never an empty list."""
    db.require_active_session(session)
    async with _client(timeout=30, trust_env=False, follow_redirects=False) as client:
        response = await client.post(f"{NAVIDROME_URL}/rest/{verb}",
            params=list(auth_params(session['username'], session['salt'], session['token']).items()),
            content=urlencode(pairs),
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        response.raise_for_status()
    body = response.json().get('subsonic-response', {})
    if body.get('status') != 'ok':
        if verb == 'getPlaylist' and str(body.get('error', {}).get('code')) == '70':
            raise HTTPException(404, 'playlist not found')
        raise HTTPException(502, 'playlist service unavailable')
    db.require_active_session(session)
    return body


async def import_playlist_request(verb, session, pairs):
    return (await subsonic_request(verb, session, pairs)).get('playlist', {})


async def owned_playlist(playlist_id, session):
    playlist = await import_playlist_request('getPlaylist', session, [('id', playlist_id)])
    if playlist.get('owner') != session['username']:
        raise HTTPException(403, 'only the owner can complete this playlist')
    return playlist
