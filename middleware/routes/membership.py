"""Small, owner-scoped replies for the player and the playlist picker."""
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

import db
from auth import get_current_session
from homelab.models import owner
from routes.playlist_edit import LIBRARY_SONG, playlist_lock, updating_playlist
from services import navidrome_client as nd

router = APIRouter(prefix="/api/playlists")


@dataclass
class Index:
    stamps: dict = field(default_factory=dict)
    contents: dict = field(default_factory=dict)
    by_song: dict = field(default_factory=lambda: defaultdict(set))

    def replace(self, key, songs, stamp):
        for song in self.contents.pop(key, set()):
            self.by_song[song].discard(key)
            if not self.by_song[song]:
                del self.by_song[song]
        self.stamps.pop(key, None)
        if songs is not None:
            self.contents[key] = songs
            self.stamps[key] = stamp
            for song in songs:
                self.by_song[song].add(key)


_indices = OrderedDict()


@router.get("/membership")
async def membership(song: str = Query(min_length=1, max_length=128), summary: bool = False,
                     sess=Depends(get_current_session)):
    user = owner(sess)
    async with playlist_lock(("membership", user)), nd.connection_scope():
        index = _indices.setdefault(user, Index())
        _indices.move_to_end(user)
        if len(_indices) > 8:
            _indices.popitem(last=False)
        listing = await nd.subsonic_request("getPlaylists", sess, [])
        own = {p["id"]: (p.get("changed"), p.get("songCount")) for p in
               listing.get("playlists", {}).get("playlist", []) if p.get("owner") == sess["username"]}
        for key in index.stamps.keys() - own.keys():
            index.replace(key, None, None)
        for key, stamp in own.items():
            if stamp != index.stamps.get(key) or stamp == (None, None):
                playlist = await nd.owned_playlist(key, sess)
                index.replace(key, {s["id"] for s in playlist.get("entry", [])}, stamp)
        track = await nd.subsonic_request("getSong", sess, [("id", song)])
        favorite = bool(track.get("song", {}).get("starred"))
        ids = index.by_song.get(song, ())
        db.require_active_session(sess)
        return {"saved": favorite or bool(ids)} if summary else {"favorite": favorite, "playlists": sorted(ids)}


def forget(user):
    """Rebuild this user's index on the next question. Needed after deleting a song: Navidrome hides it from its
    playlists but leaves their "changed" and "songCount" as they were, so the index would keep saying it is saved."""
    _indices.pop(user, None)


def invalidate_playlist(user, playlist_id):
    index = _indices.get(user)
    if index is not None:
        index.replace(playlist_id, None, None)


class Selection(BaseModel):
    song: str = Field(min_length=1, max_length=128, pattern=LIBRARY_SONG)
    included: bool


@router.put("/{playlist_id}/membership")
async def change(playlist_id: str, body: Selection, sess=Depends(get_current_session)):
    user = owner(sess)
    async with updating_playlist(user, playlist_id):
        current = await nd.owned_playlist(playlist_id, sess)
        positions = [i for i, s in enumerate(current.get("entry", [])) if s["id"] == body.song]
        pairs = []
        if body.included and not positions:
            pairs = [("songIdToAdd", body.song)]
        elif not body.included:
            pairs = [("songIndexToRemove", str(i)) for i in reversed(positions)]
        if pairs:
            await nd.import_playlist_request("updatePlaylist", sess, [("playlistId", playlist_id), *pairs])
        return {"ok": True}
