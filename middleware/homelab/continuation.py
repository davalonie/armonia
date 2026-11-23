"""«Continuar con musica similar»: a small batch of related songs when a queue ends.

Prefer the account's generated playlists. A selected YouTube recording can also seed its own radio.
"""
import json
import random
import time

from requests import RequestException
from ytmusicapi.exceptions import YTMusicError

import db
from homelab import generated_playlists as generated
from homelab import matcher, store

KEY = "setting:continue_similar"
BATCH = 5


def enabled(user):
    with db._conn() as c:
        row = c.execute("SELECT payload FROM music_preferences WHERE owner=? AND key=?", (user, KEY)).fetchone()
    return True if not row else bool(json.loads(row["payload"]))


def set_enabled(sess, user, value):
    with db.active_session(sess) as c:
        c.execute(
            "INSERT INTO music_preferences VALUES (?,?,?,?) ON CONFLICT(owner,key) DO UPDATE SET "
            "payload=excluded.payload,updated_at=excluded.updated_at",
            (user, KEY, json.dumps(bool(value)), time.time()),
        )


def _names(artist):
    return matcher.credits({"title": "x", "artist": artist or ""})[1]


def batch(user, artists, exclude, limit=BATCH, rng=random):
    """Up to `limit` songs: lists that involve the artists just heard first, then the rest."""
    generated.init()
    with store.connection() as c:
        rows = c.execute(
            "SELECT key,name,items FROM generated_playlists WHERE owner=? AND key NOT LIKE '@%' AND state='ready'",
            (user,),
        ).fetchall()
    heard = set().union(*[_names(a) for a in artists]) if artists else set()
    related, other, seen = [], [], set(exclude)
    for row in rows:
        items = json.loads(row["items"])
        # A "Mix <artist>" list is about that artist even when none of its songs are theirs.
        about = bool(heard & _names(row["name"].removeprefix("Mix ")))
        about = about or any(heard & _names(i["track"]["artist"]) for i in items)
        for item in items:
            track = item["track"]
            ident = f'{track["source"]}:{track["source_id"]}'
            if ident in seen:
                continue
            seen.add(ident)
            (related if about else other).append({"track": track, "cover": item.get("cover")})
    rng.shuffle(related)
    rng.shuffle(other)
    chosen, per_artist = [], {}
    for item in related + other:  # Variety: at most two songs by one artist in a batch.
        name = min(_names(item["track"]["artist"]) or {""})
        if per_artist.get(name, 0) >= 2:
            continue
        per_artist[name] = per_artist.get(name, 0) + 1
        chosen.append(item)
        if len(chosen) == limit:
            break
    return chosen


def radio(video_id, exclude):
    """A new listener may have no generated playlists yet. Ask for this recording's radio."""
    from services.ytdlp_service import _music_search_client

    if not generated._external_allowed(video_id):
        return []
    try:
        with generated.ytdlp_service.search_connection_scope():
            response = _music_search_client().get_watch_playlist(videoId=video_id, radio=True, limit=12)
    except (RequestException, YTMusicError, KeyError, ValueError, TypeError, IndexError):
        return []
    rows = response.get("tracks") if isinstance(response, dict) else None
    if not isinstance(rows, list):
        return []
    seen = {f"youtube:{video_id}", *exclude}
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ident = row.get("videoId")
        key = f"youtube:{ident}"
        if not isinstance(ident, str) or len(ident) != 11 or key in seen or not generated._external_allowed(ident):
            continue
        artist = ", ".join(a["name"] for a in row.get("artists") or [] if isinstance(a, dict) and isinstance(a.get("name"), str))
        album = row.get("album")
        track = generated._track("youtube", ident, row.get("title"), artist, album.get("name") if isinstance(album, dict) else None, None)
        if track:
            seen.add(key)
            items.append(generated._item(track))
        if len(items) == BATCH:
            break
    return items


async def library_followup(sess, artist, exclude):
    """A new account may still have other playable recordings by the artist in its own library."""
    wanted = _names(artist)
    if not wanted:
        return []
    rows = await generated._local_songs(artist, sess)
    seen = set(exclude)
    items = []
    for row in rows:
        if not wanted.intersection(_names(row.get("artist"))):
            continue
        track = generated._track("navidrome", row.get("id"), row.get("title"), row.get("artist"),
                                 row.get("album"), row.get("duration"))
        if not track:
            continue
        key = f"navidrome:{track['source_id']}"
        if key not in seen:
            seen.add(key)
            items.append(generated._item(track))
            if len(items) == BATCH:
                break
    return items
