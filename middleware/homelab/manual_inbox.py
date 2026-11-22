"""Private references for omitted imports, independent of import history and audio."""
import json
import time
import uuid

from fastapi import HTTPException

import db
from homelab.models import owner


def enqueue_omitted(connection, job, index):
    """Called only for an explicit skip, in the import checkpoint transaction."""
    track = job.items[index]["track"]
    payload = {
        "track": {key: track.get(key) for key in ("title", "artist", "album", "duration")},
        "originName": job.name,
        "originImportId": job.import_id,
        "originIndex": index,
        "status": "pending",
        "songId": None,
        "error": None,
    }
    connection.execute(
        "INSERT INTO manual_inbox(id,owner,origin_import_id,origin_index,payload,revision,updated_at) "
        "VALUES(?,?,?,?,?,0,?) ON CONFLICT(owner,origin_import_id,origin_index) DO NOTHING",
        (str(uuid.uuid4()), job.username, job.import_id, index, json.dumps(payload), time.time()),
    )


def identity(sess):
    db.require_active_session(sess)
    return "nd:" + owner(sess)


def owned(ident, sess, revision=None):
    user = identity(sess)
    with db._conn() as connection:
        row = connection.execute("SELECT * FROM manual_inbox WHERE id=? AND owner=?", (ident, user)).fetchone()
    if row is None:
        raise HTTPException(404, "pending reference not found")
    item = {**json.loads(row["payload"]), "id": row["id"], "revision": row["revision"]}
    if revision is not None and revision != item["revision"]:
        raise HTTPException(409, "pending reference changed; reload before continuing")
    return item


def public(item):
    return {key: item.get(key) for key in (
        "id", "track", "originName", "originImportId", "originIndex", "status", "songId", "revision", "error",
    )}


def list_items(sess):
    user = identity(sess)
    with db._conn() as connection:
        rows = connection.execute("SELECT * FROM manual_inbox WHERE owner=? ORDER BY updated_at DESC", (user,)).fetchall()
    return [public({**json.loads(row["payload"]), "id": row["id"], "revision": row["revision"]}) for row in rows]


def update(item, sess, **changes):
    user = identity(sess)
    updated = {**item, **changes, "revision": item["revision"] + 1}
    payload = {key: value for key, value in updated.items() if key not in {"id", "revision"}}
    with db.active_session(sess) as connection:
        cursor = connection.execute(
            "UPDATE manual_inbox SET payload=?,revision=?,updated_at=? WHERE id=? AND owner=? AND revision=?",
            (json.dumps(payload), updated["revision"], time.time(), item["id"], user, item["revision"]),
        )
        if cursor.rowcount != 1:
            raise HTTPException(409, "pending reference changed; reload before continuing")
    return updated


def remove(ident, revision, sess):
    user = identity(sess)
    owned(ident, sess, revision)
    with db.active_session(sess) as connection:
        cursor = connection.execute("DELETE FROM manual_inbox WHERE id=? AND owner=? AND revision=?", (ident, user, revision))
        if cursor.rowcount != 1:
            raise HTTPException(409, "pending reference changed; reload before continuing")
