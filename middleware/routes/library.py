import json
import re
import time
from contextlib import nullcontext
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

import db
from auth import get_current_session
from config import NAVIDROME_URL
from homelab import generated_playlists, store
from homelab.models import Track, owner
from routes.playlist_edit import updating_playlist
from services import navidrome_client
from services.navidrome_client import auth_params
from services.tagger_service import DEFAULT_ALBUM

router = APIRouter()

# Subsonic endpoints are flat verb names (e.g. getArtists, getCoverArt.view).
# Require a leading letter and at most one dotted suffix so `..`/slashes can't
# reach other Navidrome paths outside /rest/.
_SUBSONIC_VERB_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(\.[A-Za-z]+)?$")


@router.get("/api/library/{subpath:path}")
async def library_proxy(
    subpath: str, request: Request, sess: dict = Depends(get_current_session)
):
    if not _SUBSONIC_VERB_RE.match(subpath):
        raise HTTPException(status_code=400, detail="invalid library path")
    if subpath.split('.')[0].lower() in {'stream', 'download'}:
        raise HTTPException(400, "use the dedicated authenticated audio endpoint")
    # Strip our auth params from forwarded query; auth_params() wins
    forwarded = [
        (k, v) for k, v in request.query_params.multi_items()
        if k.lower() not in ("session", "key", "u", "t", "s", "v", "c", "f", "p", "jwt", "token", "account")
    ]
    params = forwarded + list(auth_params(sess["username"], sess["salt"], sess["token"]).items())
    verb = subpath.split('.')[0]
    # Covers: the phone keeps them and asks again only with what it has (Navidrome answers 304 Not Modified,
    # a few hundred bytes instead of the image). Song covers ("mf-<id>") keep their name when they change.
    cover = verb == "getCoverArt"
    conditional = {h: request.headers[h] for h in ("if-none-match", "if-modified-since")
                   if cover and h in request.headers}
    playlist_id = request.query_params.get('playlistId') or request.query_params.get('id')
    guard = updating_playlist(sess.get("user_id"), playlist_id) if playlist_id and verb in {'createPlaylist','updatePlaylist','deletePlaylist'} else nullcontext()
    async with guard:
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
            async with client.stream("GET",
                f"{NAVIDROME_URL}/rest/{subpath}",
                params=params,
                headers=conditional,
            ) as upstream:
                content = bytearray()
                async for chunk in upstream.aiter_bytes(64 * 1024):
                    content.extend(chunk)
                    if len(content) > 8 * 1024**2:
                        raise HTTPException(502, "library response exceeds metadata limit; reduce page size")
    if verb == "getAlbumList2" and upstream.status_code == 200 and request.headers.get("x-armonia-albums") == "1":
        try:
            result = json.loads(content)
            page = result["subsonic-response"].get("albumList2")
        except (ValueError, KeyError, AttributeError, TypeError) as exc:
            raise HTTPException(502, "invalid upstream album metadata") from exc
        if isinstance(page, dict):
            page["defaultAlbum"] = DEFAULT_ALBUM
            content = json.dumps(result, separators=(",", ":")).encode()
    validators = {h: upstream.headers[h] for h in ("etag", "last-modified") if cover and h in upstream.headers}
    return Response(
        content=bytes(content),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
        headers=validators,
    )


class RecentPlaylist(BaseModel):
    kind: Literal['local', 'mixed', 'generated']
    id: str = Field(min_length=1, max_length=128)


@router.post('/api/recent-playlists')
async def remember_playlist(body: RecentPlaylist, sess=Depends(get_current_session)):
    db.require_active_session(sess)
    if body.kind == 'local':
        playlist = await navidrome_client.owned_playlist(body.id, sess)
    elif body.kind == 'generated':
        playlist = generated_playlists.detail(owner(sess), body.id)
    else:
        playlist = store.playlist(owner(sess), body.id)
    value = {**body.model_dump(), 'name': playlist['name'], 'coverArt': playlist.get('coverArt')}
    with db.active_session(sess) as c:
        c.execute('INSERT INTO music_preferences VALUES (?,?,?,?) ON CONFLICT(owner,key) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at',
                  (owner(sess), 'recent:'+body.kind+':'+body.id, json.dumps(value), time.time()))
        c.execute("DELETE FROM music_preferences WHERE owner=? AND key LIKE 'recent:%' AND key NOT IN (SELECT key FROM music_preferences WHERE owner=? AND key LIKE 'recent:%' ORDER BY updated_at DESC LIMIT 20)", (owner(sess), owner(sess)))
    return {'ok':True}


@router.get('/api/recent-playlists')
def recent_playlists(sess=Depends(get_current_session), x_music_client: str | None = Header(default=None), kinds: str = ''):
    with db._conn() as c:
        rows = c.execute("SELECT payload,updated_at FROM music_preferences WHERE owner=? AND key LIKE 'recent:%' ORDER BY updated_at DESC LIMIT 12", (owner(sess),)).fetchall()
    result = []
    for r in rows:
        entry = {**json.loads(r['payload']), 'played_at': r['updated_at']}
        # Artwork comes from the list as it is now; a list deleted since it was played is not offered.
        try:
            if entry['kind'] == 'mixed':
                current = store.playlist(owner(sess), entry['id'])
                entry.update(name=current['name'], covers=generated_playlists.cover_refs(current['items']))
            elif entry['kind'] == 'generated':
                # Android 0.2.0 only knows local and mixed lists; newer clients ask for this kind.
                if x_music_client != 'web' and kinds != 'generated':
                    continue
                current = generated_playlists.detail(owner(sess), entry['id'])
                entry.update(name=current['name'], covers=current['covers'])
        except HTTPException:
            continue
        result.append(entry)
    return {'playlists': result}


class TrackPreference(BaseModel):
    track: Track
    favorite: bool = False
    rating: int = Field(default=0, ge=0, le=5)


@router.get('/api/track-preferences')
def track_preferences(sess=Depends(get_current_session)):
    with db._conn() as c:
        rows = c.execute("SELECT payload FROM music_preferences WHERE owner=? AND key LIKE 'track:%' ORDER BY updated_at DESC LIMIT 5000", (owner(sess),)).fetchall()
    return {'items':[json.loads(r['payload']) for r in rows]}


@router.put('/api/track-preferences')
def set_track_preference(body: TrackPreference, sess=Depends(get_current_session)):
    if body.track.source == 'navidrome':
        raise HTTPException(400, 'use native library favorites and rating')
    value = body.model_dump(mode='json')
    key = f'track:{body.track.source}:{body.track.source_id}'
    with db.active_session(sess) as c:
        if not body.favorite and not body.rating:
            c.execute('DELETE FROM music_preferences WHERE owner=? AND key=?', (owner(sess), key))
        else:
            count = c.execute("SELECT count(*) FROM music_preferences WHERE owner=? AND key LIKE 'track:%'", (owner(sess),)).fetchone()[0]
            exists = c.execute('SELECT 1 FROM music_preferences WHERE owner=? AND key=?', (owner(sess),key)).fetchone()
            if count >= 5000 and not exists:
                raise HTTPException(409, 'preference storage limit reached')
            c.execute('INSERT INTO music_preferences VALUES (?,?,?,?) ON CONFLICT(owner,key) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at', (owner(sess),key,json.dumps(value),time.time()))
    return value
