import asyncio
import csv
import io
import json
import logging
import math
import os
import re
import time
from pathlib import Path

import httpx

from services import tagger_service

log = logging.getLogger(__name__)

# A browser-like UA keeps Spotify from serving us a stripped/blocked response.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class SpotifyError(Exception):
    """Raised for any Spotify import failure (bad URL, private playlist, parse error)."""


def parse_playlist_id(url: str) -> str | None:
    """Extract a playlist id from a share URL or URI.

    Handles open.spotify.com/playlist/<id>, /intl-xx/playlist/<id>, and
    spotify:playlist:<id>.
    """
    if not url:
        return None
    m = re.search(r"playlist[/:]([A-Za-z0-9]+)", url.strip())
    return m.group(1) if m else None


def _extract_next_data(html: str) -> dict | None:
    m = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


async def _fetch_embed(url: str) -> dict:
    """Return public playlist metadata, including duration in seconds if present.

    Reads the public embed page (no API key / Premium needed). Only works for
    public playlists; the embed JSON carries title, artist and duration in ms.
    """
    playlist_id = parse_playlist_id(url)
    if not playlist_id:
        raise SpotifyError("That doesn't look like a Spotify playlist link")

    try:
        async with httpx.AsyncClient(
            timeout=20, headers={"User-Agent": _UA}, follow_redirects=False, trust_env=False
        ) as client:
            async with client.stream("GET", f"https://open.spotify.com/embed/playlist/{playlist_id}") as r:
                r.raise_for_status()
                content = bytearray()
                async for chunk in r.aiter_bytes(64 * 1024):
                    content.extend(chunk)
                    if len(content) > 4 * 1024**2:
                        raise SpotifyError("Playlist response exceeds the size limit")
                html = content.decode("utf-8")
    except Exception as e:
        raise SpotifyError("Couldn't read this public Spotify playlist") from e

    data = _extract_next_data(html)
    if not data:
        raise SpotifyError("Couldn't read playlist data from Spotify (page format may have changed)")

    try:
        entity = data["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, TypeError) as e:
        log.warning("spotify embed: unexpected JSON shape for playlist %s", playlist_id)
        raise SpotifyError("Couldn't find the tracks — make sure the playlist is public") from e

    name = entity.get("name") or entity.get("title") or "Imported playlist"
    track_list = entity.get("trackList") or []
    if len(track_list) > 500:
        raise SpotifyError("Import is limited to 500 tracks")

    tracks = [_track(t, i, embed=True) for i, t in enumerate(track_list)]
    if not tracks:
        raise SpotifyError("Playlist has no tracks, or it isn't public")
    total = next((entity[k] for k in ("totalCount", "trackCount", "totalTracks")
                  if type(entity.get(k)) is int and entity[k] >= len(tracks)), None)
    # An embed is a view, not a paginated catalog. Unknown completeness must
    # remain unknown, including below the often observed 99/100 boundary.
    return _result(name, tracks, total, "embed", None if total == len(tracks) else "embed_partial_or_unknown")


_COLUMNS = {
    "title": ("track name", "title", "name", "track", "nombre de la canción"),
    "artist": ("artist name(s)", "artist names", "artist name", "artists", "artist", "nombre(s) del artista"),
    "album": ("album name", "album", "nombre del álbum"),
    "album_artist": ("album artist name(s)", "album artist names", "album artist name", "album artist",
                     "nombre(s) del artista del álbum"),
    "duration": ("duration (ms)", "track duration (ms)", "duration_ms", "duration ms", "duración de la canción (ms)"),
    "isrc": ("isrc",),
    "track_number": ("track number", "número de pista"),
    "disc_number": ("disc number", "número de disco"),
    "release_date": ("release date", "album release date", "fecha de lanzamiento"),
    "source_id": ("track uri", "spotify uri", "uri", "spotify id", "track id", "uri de la canción"),
}
# One imported playlist from the owner's own export or sign-in. Large enough for a whole
# «Liked» library; each position costs a search at most, and progress writes are bounded.
FILE_LIMIT = 5000


def _names(value: str) -> list[str]:
    """Exportify joins names with ", " (older exports with ";") and writes a comma inside a name as "\\,"."""
    return [a.replace("\\,", ",").strip() for a in re.split(r"(?<!\\)[;,]", value) if a.strip()]


def parse_export(text: str, name: str) -> dict:
    """A playlist exported by its owner: CSV with a header row, or one "Artist - Title" per line.

    This is the complete-recovery path when the public embed only shows a partial view.
    Order and intentional repeats are kept; rows without a title stay as unavailable
    positions instead of being dropped, so counts remain comparable with the source.
    """
    text = text.lstrip("\ufeff")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise SpotifyError("El archivo no contiene canciones")
    tracks = []
    try:
        header = [h.strip().casefold() for h in next(csv.reader([lines[0]]))]
    except csv.Error as exc:
        raise SpotifyError("No se pudo leer el archivo") from exc
    column = {key: next((header.index(n) for n in names if n in header), None) for key, names in _COLUMNS.items()}
    if column["title"] is not None and column["artist"] is not None:
        try:
            rows = list(csv.reader(io.StringIO("\n".join(text.splitlines()[1:]))))
        except csv.Error as exc:
            raise SpotifyError("No se pudo leer el archivo") from exc
        for row in rows:
            if not any(cell.strip() for cell in row):
                continue

            def cell(key, row=row):
                index = column[key]
                return row[index].strip() if index is not None and index < len(row) else ""
            try:
                ms = float(cell("duration"))
            except ValueError:
                ms = None
            # Exportify joins artists with ", " and writes a comma inside a name as "\,".
            artists = _names(cell("artist"))
            tracks.append({
                "title": cell("title") or "Elemento no disponible", "artist": ", ".join(artists) or "Unknown",
                # Kept as a list too: once joined, a name that contains a comma cannot be told
                # apart from two performers, and the album would be filed under all of them.
                "artists": artists, "album_artist": ", ".join(_names(cell("album_artist"))) or None,
                "album": cell("album"), "duration": ms / 1000 if ms and math.isfinite(ms) and 0 < ms <= 86400000 else None,
                "source_position": len(tracks), "source_id": cell("source_id") or None, "isrc": cell("isrc") or None,
                "details": tagger_service.clean_details({
                    "track": cell("track_number"), "disc": cell("disc_number"), "date": cell("release_date")}),
                "source_unavailable": not cell("title"),
            })
    else:
        for line in lines:
            artist, separator, title = line.strip().partition(" - ")
            if not separator or not artist.strip() or not title.strip():
                raise SpotifyError(f'Linea {len(tracks) + 1}: se esperaba "Artista - Titulo" o un CSV con cabecera')
            tracks.append({"title": title.strip()[:300], "artist": artist.strip()[:300], "album": "", "duration": None,
                           "source_position": len(tracks), "source_id": None, "isrc": None, "source_unavailable": False})
    if not tracks:
        raise SpotifyError("El archivo no contiene canciones")
    total = len(tracks)
    tracks = tracks[:FILE_LIMIT]
    return _result(name.strip()[:150] or "Playlist importada", tracks, total, "file",
                   None if total == len(tracks) else "resource_limit")


_client_token = {"value": None, "expires": 0.0, "file": None}


async def _api_token():
    """Operator-supplied access: a static token file, or an application's client credentials.

    Client credentials is Spotify's documented application flow; the short-lived token is
    kept in memory only and renewed when it expires. No token is discovered from web pages.
    """
    token_file = os.environ.get("MUSIC_SPOTIFY_METADATA_TOKEN_FILE")
    if token_file:
        token = Path(token_file).read_text().strip()
        if not token or len(token) > 8192:
            raise ValueError("invalid token")
        return token
    client_file = os.environ["MUSIC_SPOTIFY_CLIENT_FILE"]
    if _client_token["file"] == client_file and _client_token["expires"] - 60 > time.monotonic():
        return _client_token["value"]
    config = json.loads(Path(client_file).read_text())
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
        response = await client.post("https://accounts.spotify.com/api/token", data={"grant_type": "client_credentials"},
                                     auth=(str(config["client_id"]), str(config["client_secret"])))
        response.raise_for_status()
        data = response.json()
    token, ttl = data.get("access_token"), data.get("expires_in")
    if not isinstance(token, str) or not token or type(ttl) is not int or ttl <= 0:
        raise ValueError("invalid token response")
    _client_token.update(value=token, expires=time.monotonic() + ttl, file=client_file)
    return token


def _track(t, position, embed=False):
    t = t if isinstance(t, dict) else {}
    ms = t.get("duration" if embed else "duration_ms")
    duration = ms / 1000 if type(ms) in (int, float) and math.isfinite(ms) and 0 < ms <= 86400000 else None
    title = t.get("title" if embed else "name")
    artists = [a.get("name") for a in (t.get("artists") or []) if isinstance(a, dict) and a.get("name")]
    album = t.get("album") if isinstance(t.get("album"), dict) and not embed else {}
    owners = [a.get("name") for a in (album.get("artists") or []) if isinstance(a, dict) and a.get("name")]
    return {
        "title": title or "Elemento no disponible", "artist": ", ".join(artists) or t.get("subtitle") or "Unknown",
        "artists": artists, "album_artist": ", ".join(owners) or None,
        "album": album.get("name") or "",
        "duration": duration, "source_position": position,
        "source_id": t.get("uri") or t.get("id"),
        "isrc": (t.get("external_ids") or {}).get("isrc"),
        "details": tagger_service.clean_details({
            "track": t.get("track_number"), "disc": t.get("disc_number"), "date": album.get("release_date")}),
        "source_unavailable": not title or (not embed and t.get("type", "track") != "track"),
    }


def _result(name, tracks, total, source, warning=None, snapshot=None):
    return {"name": name, "tracks": tracks, "source_total": total,
            "retrieved": len(tracks), "source_complete": warning is None and total == len(tracks),
            "source_warning": warning, "metadata_source": source, "snapshot": snapshot}


async def _json(client, url):
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        content = bytearray()
        async for chunk in response.aiter_bytes(65536):
            content.extend(chunk)
            if len(content) > 4 * 1024**2:
                raise SpotifyError("Playlist response exceeds the size limit")
        return json.loads(content)


async def fetch_playlist(url: str) -> dict:
    """Public embed by default; official pagination only with explicit operator opt-in.

    No token discovery, preview extraction or hidden user OAuth. The token file
    is never returned/persisted in import jobs. Each page is fetched at its exact
    expected offset, and remote `next` URLs are never followed.
    """
    if not os.environ.get("MUSIC_SPOTIFY_METADATA_TOKEN_FILE") and not os.environ.get("MUSIC_SPOTIFY_CLIENT_FILE"):
        return await _fetch_embed(url)
    ident = parse_playlist_id(url)
    if not ident:
        raise SpotifyError("Invalid Spotify playlist link")
    try:
        token = await _api_token()
        async with asyncio.timeout(90), httpx.AsyncClient(timeout=20, headers={"Authorization": "Bearer " + token},
                                     follow_redirects=False, trust_env=False) as client:
            base = f"https://api.spotify.com/v1/playlists/{ident}"
            meta = await _json(client, base + "?fields=name,snapshot_id,tracks.total,items.total")
            total = (meta.get("items") or meta.get("tracks") or {}).get("total")
            if type(total) is not int or total < 0:
                raise SpotifyError("Provider did not supply the playlist total")
            tracks, warning = [], None
            # 500 is a resource budget, never an assertion of completeness.
            while len(tracks) < min(total, 500):
                offset = len(tracks)
                try:
                    page = await _json(client, base + f"/items?limit=50&offset={offset}")
                    entries = page.get("items") or []
                    if page.get("offset") != offset or page.get("total") != total or not entries:
                        warning = "page_inconsistent"
                        break
                    if len(entries) > 50 or offset + len(entries) > total:
                        warning = "page_inconsistent"
                        break
                    tracks.extend(_track(e.get("item", e.get("track")) if isinstance(e, dict) else None, offset + i)
                                  for i, e in enumerate(entries))
                except (httpx.HTTPError, ValueError, SpotifyError):
                    warning = "page_failed"
                    break
            if len(tracks) < total and warning is None:
                warning = "resource_limit"
            # Detect edits made during pagination before claiming completeness.
            try:
                check = await _json(client, base + "?fields=snapshot_id")
            except (httpx.HTTPError, ValueError, SpotifyError):
                warning = warning or "snapshot_unverified"
            else:
                if check.get("snapshot_id") != meta.get("snapshot_id"):
                    raise SpotifyError("Playlist changed during retrieval; retry")
            return _result(meta.get("name") or "Imported playlist", tracks, total, "api", warning,
                           meta.get("snapshot_id"))
    except TimeoutError:
        if 'tracks' in locals() and tracks:
            return _result(meta.get("name") or "Imported playlist", tracks, total, "api", "time_budget", meta.get("snapshot_id"))
        raise SpotifyError("Spotify metadata retrieval timed out") from None
    except SpotifyError:
        raise
    except Exception as exc:
        raise SpotifyError("Couldn't read the configured Spotify metadata API") from exc
