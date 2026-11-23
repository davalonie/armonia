"""Inicio: generated personal playlists and similar artists, private per user."""
from anyio import to_thread
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

import db
from auth import get_current_session
from homelab import continuation, releases
from homelab import generated_playlists as generated
from homelab.models import owner
from routes import discover

router = APIRouter(prefix="/api/home", tags=["home"])


@router.get("/playlists")
async def playlists(sess=Depends(get_current_session)):
    user = owner(sess)
    generated.refresh(user, sess)
    return {"playlists": generated.summaries(user), "status": generated.status(user)}


@router.post("/playlists/refresh", status_code=202)
async def refresh(sess=Depends(get_current_session)):
    db.require_active_session(sess)
    generated.refresh(owner(sess), sess, force=True)
    return {"status": generated.status(owner(sess))}


@router.post("/weekly", status_code=202)
async def activate_weekly(sess=Depends(get_current_session)):
    """Enable the private, download-free Aurral flow, then build the playlist from it."""
    await discover.weekly(sess)
    user = owner(sess)
    generated._last_manual.pop(user, None)
    generated.refresh(user, sess, force=True)
    return {"status": generated.status(user)}


@router.get("/artists")
def artists(sess=Depends(get_current_session)):
    return {"artists": generated.artists(owner(sess))}


@router.get("/playlists/{key}")
def playlist(key: str, sess=Depends(get_current_session)):
    return generated.detail(owner(sess), key)


@router.post("/playlists/{key}/save", status_code=201)
def save(key: str, sess=Depends(get_current_session)):
    db.require_active_session(sess)
    saved = generated.save_copy(owner(sess), key)
    return {"id": saved["id"], "name": saved["name"], "count": len(saved["items"])}


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    continue_similar: bool


@router.get("/settings")
def settings(sess=Depends(get_current_session)):
    return {"continue_similar": continuation.enabled(owner(sess))}


@router.put("/settings")
def write_settings(body: Settings, sess=Depends(get_current_session)):
    continuation.set_enabled(sess, owner(sess), body.continue_similar)
    return {"continue_similar": body.continue_similar}


class Continue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artists: list[str] = Field(default_factory=list, max_length=10)
    exclude: list[str] = Field(default_factory=list, max_length=600)
    videoId: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{11}$")


@router.post("/continue")
async def continue_similar(body: Continue, sess=Depends(get_current_session)):
    """Related songs to follow a finished queue. Read-only: no list, queue or statistic is written."""
    db.require_active_session(sess)
    user = owner(sess)
    if not continuation.enabled(user):
        return {"enabled": False, "items": []}
    names = [a[:300] for a in body.artists]
    excluded = {e[:140] for e in body.exclude}
    items = continuation.batch(user, names, excluded)
    if not items:
        if body.videoId:
            items = await to_thread.run_sync(continuation.radio, body.videoId, excluded)
        elif names and any(key.startswith("navidrome:") for key in excluded):
            items = await continuation.library_followup(sess, names[0], excluded)
        db.require_active_session(sess)
        if not continuation.enabled(user):
            return {"enabled": False, "items": []}
    return {"enabled": True, "items": items}


@router.get("/releases")
async def calendar(sess=Depends(get_current_session)):
    return releases.listing(sess, owner(sess))


@router.get("/releases/{key}/cover")
async def cover(key: str, sess=Depends(get_current_session)):
    data = await releases.cover(owner(sess), key)
    db.require_active_session(sess)
    return Response(data, media_type="image/jpeg")


@router.get("/releases/{key}")
async def release_tracks(key: str, sess=Depends(get_current_session)):
    return releases.tracks(sess, owner(sess), key)
