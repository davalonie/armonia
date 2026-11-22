"""Resolve local identifiers through the listener's own Subsonic credentials.

Navidrome 0.64.2 song.artists contains local IDs, NOT artist MusicBrainz IDs.
getArtist supplies the latter without enabling external metadata services.
"""
import re
from uuid import UUID

from fastapi import HTTPException

from config import NAVIDROME_URL
from homelab.integrations import request_json
from homelab.models import Track
from services.navidrome_client import auth_params


def mbid(value):
    try:
        return str(UUID(value)) if value else None
    except (ValueError, TypeError, AttributeError):
        return None


async def local_track(track_id, session):
    auth = auth_params(session["username"], session["salt"], session["token"])
    async def query(verb, ident):
        data = await request_json(NAVIDROME_URL + "/rest/" + verb, params={**auth, "id": ident})
        body = data.get("subsonic-response", {})
        if body.get("status") != "ok":
            if body.get("error", {}).get("code") == 70:
                return None  # Deleted/unavailable after an offline listen.
            raise HTTPException(502, "local recording metadata unavailable")
        return body
    song = await query("getSong", track_id)
    if not song:
        return None
    song = song["song"]
    ids = [a.get("id") for a in song.get("artists", [])] or [song.get("artistId")]
    artists = []
    for ident in list(dict.fromkeys(ids))[:20]:
        if ident and len(artists) < 20:
            data = await query("getArtist", ident)
            value = mbid((data or {}).get("artist", {}).get("musicBrainzId"))
            if value:
                artists.append(value)
    isrc = next((value for value in song.get("isrc", []) if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}[0-9]{7}", value)), None)
    return Track(source="navidrome", source_id=track_id, title=song["title"], artist=song.get("artist") or "Unknown",
        album=song.get("album") or "", duration=song.get("duration") or None,
        artist_mbids=artists, recording_mbid=mbid(song.get("musicBrainzId")), isrc=isrc)
