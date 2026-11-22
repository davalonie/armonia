"""«Continuar con música similar»: a small batch of related songs when a queue ends.

Songs come from the user's own generated lists (already built from Aurral and resolved to playable
sources), so nothing new is asked of any provider and no listening history leaves the server.
"""
import json
import random
import time

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
