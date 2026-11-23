"""A separate, versioned SQLite database; no writes into upstream service DBs."""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

from fastapi import HTTPException

import db

_SCHEMA = '''
CREATE TABLE IF NOT EXISTS playlists (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, revision INTEGER NOT NULL,
 items TEXT NOT NULL, updated INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS playlists_owner ON playlists(owner);
CREATE TABLE IF NOT EXISTS credentials (
 owner TEXT NOT NULL, service TEXT NOT NULL, remote_id TEXT NOT NULL, token TEXT NOT NULL,
 PRIMARY KEY(owner, service), UNIQUE(service, remote_id)
);
CREATE TABLE IF NOT EXISTS matches (
 owner TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, expires INTEGER NOT NULL,
 PRIMARY KEY(owner, key)
);
CREATE TABLE IF NOT EXISTS recommendations (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, created INTEGER NOT NULL, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS play_events (
 owner TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, created INTEGER NOT NULL,
 PRIMARY KEY(owner, id)
);
CREATE TABLE IF NOT EXISTS outbox (
 owner TEXT NOT NULL, event_id TEXT NOT NULL, destination TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
 next_try INTEGER NOT NULL DEFAULT 0, error TEXT,
 PRIMARY KEY(owner, event_id, destination),
 FOREIGN KEY(owner,event_id) REFERENCES play_events(owner,id) ON DELETE CASCADE
);
'''


def init():
    with connection() as c:
        version = c.execute("PRAGMA user_version").fetchone()[0]
        if version > 4:
            raise RuntimeError("Music database is newer than this application")
        c.execute("CREATE TABLE IF NOT EXISTS playlist_covers (kind TEXT, id TEXT, owner TEXT NOT NULL, "
                  "token TEXT NOT NULL UNIQUE, image BLOB NOT NULL, PRIMARY KEY(kind,id))")
        c.execute("CREATE TABLE IF NOT EXISTS aurral_unlinked (owner TEXT PRIMARY KEY)")
        if version < 1:
            c.executescript("BEGIN IMMEDIATE;" + _SCHEMA + "PRAGMA user_version=1; COMMIT;")
        if version < 2:
            c.executescript("BEGIN IMMEDIATE; ALTER TABLE play_events ADD COLUMN canonical TEXT; PRAGMA user_version=2; COMMIT;")
        if version < 3:
            from homelab.artist_ids import remember
            c.execute("BEGIN IMMEDIATE")
            c.execute("CREATE TABLE artist_identities (owner TEXT NOT NULL,name TEXT NOT NULL,mbid TEXT NOT NULL,PRIMARY KEY(owner,name,mbid))")
            for row in c.execute("SELECT owner, COALESCE(canonical,payload) FROM play_events").fetchall():
                remember(c, row[0], json.loads(row[1])["track"])
            c.execute("PRAGMA user_version=3")
        if version < 4:
            c.commit()  # The preceding migration is independently recoverable.
            c.execute("BEGIN IMMEDIATE")
            c.execute("CREATE TABLE publication_intents (library TEXT NOT NULL, source TEXT NOT NULL, "
                      "path TEXT NOT NULL, PRIMARY KEY(library,source,path))")
            c.execute("PRAGMA user_version=4")


@contextmanager
def connection(write=False):
    path = db.DB_PATH.parent / "music.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Async routes also use this small store. Never stall their event loop for
    # fifteen seconds behind another writer; clients can retry a bounded 503.
    c = sqlite3.connect(path, timeout=.1)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA foreign_keys=ON")
        if write:
            c.execute("BEGIN IMMEDIATE")
        yield c
        c.commit()
    except sqlite3.OperationalError as exc:
        c.rollback()
        if getattr(exc, "sqlite_errorcode", 0) & 0xff in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise HTTPException(503, "music database temporarily busy", headers={"Retry-After": "1"}) from exc
        raise
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def _playlist(row):
    return {"id": row["id"], "name": row["name"], "revision": row["revision"],
            "items": json.loads(row["items"]), "updated": row["updated"]}


def playlists(user):
    with connection() as c:
        # The library index needs summaries, not up to 100,000 embedded tracks.
        # Detail/edit/playback loads one revision through playlist(user, key).
        # The first four references are read inside SQLite for the artwork mosaic.
        picks = ",".join(f"json_extract(items,'$[{i}].track.source') AS s{i},json_extract(items,'$[{i}].track.source_id') AS i{i}"
                         for i in range(4))
        rows = c.execute(
            f"SELECT id,name,revision,updated,json_array_length(items) AS item_count,{picks} "
            "FROM playlists WHERE owner=? ORDER BY updated DESC", (user,)).fetchall()
    result = []
    for r in rows:
        covers = [{"source": r[f"s{i}"], "source_id": r[f"i{i}"], "cover": None} for i in range(4) if r[f"s{i}"] and r[f"i{i}"]]
        result.append({"id": r["id"], "name": r["name"], "revision": r["revision"], "updated": r["updated"],
                       "item_count": r["item_count"], "covers": covers})
    from homelab import playlist_covers
    playlist_covers.attach(result, "mixed")
    return result


def playlist(user, key):
    with connection() as c:
        row = c.execute("SELECT * FROM playlists WHERE owner=? AND id=?", (user, key)).fetchone()
    if not row:
        raise HTTPException(404, "playlist not found")
    result = _playlist(row)
    from homelab import playlist_covers
    playlist_covers.attach([result], "mixed")
    return result


def write_playlist(user, body, key=None):
    ids = [str(i.id) for i in body.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "duplicate playlist entry id")
    with connection(write=True) as c:
        if key:
            row = c.execute("SELECT revision FROM playlists WHERE owner=? AND id=?", (user, key)).fetchone()
            if not row:
                raise HTTPException(404, "playlist not found")
            if row[0] != body.revision:
                raise HTTPException(409, "playlist changed; reload before saving")
        else:
            if body.revision != 0:
                raise HTTPException(409, "new playlists start at revision zero")
            if c.execute("SELECT count(*) FROM playlists WHERE owner=?", (user,)).fetchone()[0] >= 200:
                raise HTTPException(409, "playlist limit reached")
            key = str(uuid.uuid4())
        data = json.dumps([i.model_dump(mode="json") for i in body.items], ensure_ascii=False)
        c.execute("INSERT INTO playlists VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                  "name=excluded.name, revision=excluded.revision, items=excluded.items, updated=excluded.updated",
                  (key, user, body.name, body.revision + 1, data, int(time.time())))
    return playlist(user, key)


def delete_playlist(user, key, revision):
    with connection(write=True) as c:
        row = c.execute("SELECT revision FROM playlists WHERE owner=? AND id=?", (user, key)).fetchone()
        if not row:
            raise HTTPException(404, "playlist not found")
        if row[0] != revision:
            raise HTTPException(409, "playlist changed; reload before deleting")
        c.execute("DELETE FROM playlists WHERE owner=? AND id=?", (user, key))
        c.execute("DELETE FROM playlist_covers WHERE kind='mixed' AND id=? AND owner=?", (key, user))
