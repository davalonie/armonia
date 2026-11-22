from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_session
from homelab import store
from homelab.models import PlaylistWrite, owner
from services import navidrome_client

router = APIRouter(prefix="/api/mixed-playlists", tags=["mixed playlists"])


@router.get("")
def listing(sess=Depends(get_current_session)):
    return {"playlists": store.playlists(owner(sess))}


@router.post("", status_code=201)
def create(body: PlaylistWrite, sess=Depends(get_current_session)):
    return store.write_playlist(owner(sess), body)


@router.get("/{key}")
def get(key: UUID, sess=Depends(get_current_session)):
    return store.playlist(owner(sess), str(key))


@router.put("/{key}")
def edit(key: UUID, body: PlaylistWrite, sess=Depends(get_current_session)):
    return store.write_playlist(owner(sess), body, str(key))


@router.delete("/{key}")
def remove(key: UUID, revision: int = Query(ge=1), sess=Depends(get_current_session)):
    store.delete_playlist(owner(sess), str(key), revision)
    return {"ok": True}


class Export(BaseModel):
    revision: int = Field(ge=1)


@router.post("/{key}/export-navidrome")
async def export(key: UUID, body: Export, sess=Depends(get_current_session)):
    saved = store.playlist(owner(sess), str(key))
    if saved["revision"] != body.revision:
        raise HTTPException(409, "playlist changed; reload before exporting")
    ids = [i["track"]["source_id"] for i in saved["items"] if i["track"]["source"] == "navidrome"]
    if not ids:
        raise HTTPException(409, "playlist has no local tracks")
    result = await navidrome_client.create_playlist(saved["name"] + " (local copy)", ids,
                                                    sess["username"], sess["salt"], sess["token"])
    if not result:
        raise HTTPException(502, "Navidrome export failed")
    return {"playlistId": result, "exported": len(ids), "omitted": len(saved["items"]) - len(ids)}
