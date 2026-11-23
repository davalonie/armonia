"""Personal playlist artwork. Clients use the usual authenticated cover-art endpoint."""
import hashlib
import io

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

from homelab import store

MAX_BYTES = 8 * 1024 * 1024


def jpeg(data):
    try:
        with Image.open(io.BytesIO(data), formats=("JPEG", "PNG", "WEBP")) as image:
            if image.width * image.height > 24_000_000:
                raise HTTPException(413, "image exceeds 24 megapixels")
            image.thumbnail((640, 640))
            thumb = ImageOps.exif_transpose(image).convert("RGB")
            out = io.BytesIO()
            thumb.save(out, format="JPEG", quality=85)
            return out.getvalue()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "choose a JPEG, PNG or WebP image") from exc


def save(kind, key, user, data):
    token = "armonia-art-" + hashlib.sha256(f"{kind}/{key}/{user}/".encode() + data).hexdigest()
    with store.connection(write=True) as c:
        if kind == "mixed" and not c.execute(
            "SELECT 1 FROM playlists WHERE id=? AND owner=?", (key, user)
        ).fetchone():
            raise HTTPException(404, "playlist not found")
        c.execute("INSERT OR REPLACE INTO playlist_covers(kind,id,owner,token,image) VALUES(?,?,?,?,?)",
                  (kind, key, user, token, data))
    return token


def attach(rows, kind):
    if not rows:
        return
    ids = [r["id"] for r in rows]
    with store.connection() as c:
        covers = {}
        for offset in range(0, len(ids), 400):
            batch = ids[offset:offset+400]
            slots = ",".join("?" for _ in batch)
            covers.update(c.execute(f"SELECT id,token FROM playlist_covers WHERE kind=? AND id IN ({slots})",
                                    (kind, *batch)).fetchall())
    for row in rows:
        if row["id"] in covers:
            row["coverArt"] = covers[row["id"]]
