"""Durable HTTP publication receipts; no audio or credentials in this table."""
from fastapi import HTTPException

from homelab import store
from services import safe_files


def require_unpublished(root, source):
    with store.connection() as c:
        rows = c.execute("SELECT path FROM publication_intents WHERE library=? AND source=?",
                         (str(root), source)).fetchall()
    for row in rows:
        try:
            exists = safe_files.private_file_exists(root, row["path"])
        except (ValueError, OSError) as exc:
            raise HTTPException(409, "saved file cannot be verified in your library") from exc
        if exists:
            raise HTTPException(409, "recording already saved; rescan your library")


def record(root, source, path):
    # Guard against accidental integration misuse before persisting a receipt.
    safe_files.relative_file(root, path)
    with store.connection(write=True) as c:
        c.execute("INSERT INTO publication_intents(library,source,path) VALUES (?,?,?) "
                  "ON CONFLICT(library,source,path) DO NOTHING",
                  (str(root), source, path))
