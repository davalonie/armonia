"""Optimistic edits for native playlists. Existing Subsonic/Android API remains."""

import asyncio
from contextlib import asynccontextmanager
from typing import Annotated
from weakref import WeakValueDictionary

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_session
from services import navidrome_client as nd

router = APIRouter()
_locks = WeakValueDictionary()


def playlist_lock(playlist_id):
    if playlist_id not in _locks:
        _locks[playlist_id] = lock = asyncio.Lock()
        return lock
    return _locks[playlist_id]


@asynccontextmanager
async def updating_playlist(user, playlist_id):
    # Summary refreshes take the account lock first too. Invalidate even on an
    # upstream timeout: the provider may have committed before the reply was lost.
    from routes.membership import invalidate_playlist
    async with playlist_lock(("membership", user)), playlist_lock(playlist_id):
        try:
            yield
        finally:
            invalidate_playlist(user, playlist_id)


# Only library songs fit in a library playlist. A song not downloaded yet (the app's "preview|" and
# "external|" ids) used to be accepted, then silently dropped by Navidrome: the app said it was saved
# and the playlist did not change. Now it is refused, so the app can say so.
LIBRARY_SONG = r"^[^|]+$"


class Edit(BaseModel):
    expected: list[str] = Field(max_length=5000)
    songs: list[Annotated[str, Field(pattern=LIBRARY_SONG)]] = Field(max_length=5000)


@router.post("/api/playlists/{playlist_id}/edit")
async def edit(playlist_id: str, body: Edit, sess: dict = Depends(get_current_session)):
    async with updating_playlist(sess.get("user_id"), playlist_id):
        current = await nd.owned_playlist(playlist_id, sess)
        ids = [s["id"] for s in current.get("entry", [])]
        if ids == body.songs:
            return {"count": len(ids)}  # response lost after a successful edit
        if ids != body.expected:
            raise HTTPException(409, "playlist changed; reload before editing")
        if body.songs:
            await nd.import_playlist_request(
                "createPlaylist", sess, [("playlistId", playlist_id)] + [("songId", s) for s in body.songs]
            )
        else:
            # Navidrome treats omitted songId as "keep current contents".
            # Explicit positions are required to remove the final song(s).
            await nd.import_playlist_request(
                "updatePlaylist",
                sess,
                [("playlistId", playlist_id)] + [("songIndexToRemove", str(i)) for i in reversed(range(len(ids)))],
            )
        return {"count": len(body.songs)}
