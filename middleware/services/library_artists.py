"""Build the visible artist index from the current user's Navidrome library."""
import asyncio
import hashlib
import time
from collections import OrderedDict
from weakref import WeakValueDictionary

from fastapi import HTTPException

from services import navidrome_client as nd

_cache = OrderedDict()
_locks = WeakValueDictionary()


def artist_index(listed, songs):
    by_name = {a["name"].strip().casefold(): dict(a) for a in listed if a.get("name")}
    known = set(by_name)
    for song in songs:
        name = (song.get("artist") or "").strip().casefold()
        if name and "," not in name:
            known.add(name)
        for field in ("artists", "albumArtists"):
            known.update(a["name"].strip().casefold() for a in song.get(field) or [] if a.get("name"))
    entries = {}
    compound = set()
    for song in songs:
        artist = song.get("artist", "").strip()
        credits = [a["name"].strip() for a in song.get("artists") or [] if a.get("name")]
        owners = [a["name"].strip() for a in song.get("albumArtists") or [] if a.get("name")]
        if len(credits) > 1 and artist.casefold() not in {name.casefold() for name in credits}:
            compound.add(artist.casefold())
        album_artist = (song.get("albumArtist") or "").strip()
        names = owners or ([album_artist] if album_artist else credits) or [artist]
        if names == [artist] and "," in artist:
            parts = [p.strip() for p in artist.split(",")]
            # Old files often have one combined artist and album artist. Independent names in
            # this user's library corroborate the split; punctuation alone is ambiguous.
            if len(credits) > 1:
                names = credits
            elif all(parts) and sum(p.casefold() in known for p in parts) >= 2:
                names = parts
                compound.add(artist.casefold())
        for name in dict.fromkeys(n.casefold() for n in names if n):
            display = next(n for n in names if n.casefold() == name)
            entry = by_name.get(name) or {"id": "credit-" + hashlib.sha256(name.encode()).hexdigest(),
                                         "name": display, "albumCount": 0}
            entries.setdefault(name, (entry, {}))[1][song["id"]] = song
    for name, entry in by_name.items():
        if name not in compound:
            entries.setdefault(name, (entry, {}))
    return {entry["id"]: (entry, list(tracks.values())) for entry, tracks in entries.values()}


async def index(sess):
    async with nd.connection_scope():
        folders = (await nd.subsonic_request("getMusicFolders", sess, [])).get("musicFolders", {})
        key = (sess["id"], tuple(sorted(str(f["id"]) for f in folders.get("musicFolder", []))))
        lock = _locks.setdefault(key, asyncio.Lock())
        async with lock:
            previous = _cache.get(key)
            if previous and previous[0] > time.monotonic():
                return previous[1]
            response = await nd.subsonic_request("getArtists", sess, [])
            listed = [a for group in response.get("artists", {}).get("index", []) for a in group.get("artist", [])]
            songs = []
            seen = set()
            offset = 0
            while True:
                page = await nd.subsonic_request("search3", sess, [("query", " "), ("songOffset", str(offset)),
                    ("songCount", "500"), ("artistCount", "0"), ("albumCount", "0")])
                batch = page.get("searchResult3", {}).get("song", [])
                previous_count = len(songs)
                for song in batch:
                    ident = song.get("id")
                    if ident and ident not in seen:
                        seen.add(ident)
                        songs.append(song)
                offset += len(batch)
                if len(batch) < 500 or len(songs) == previous_count:
                    break
            data = artist_index(listed, songs)
            if len(songs) <= 10000:
                _cache[key] = time.monotonic() + 60, data
                _cache.move_to_end(key)
                if len(_cache) > 4:
                    _cache.popitem(last=False)
            return data


async def browse(sess, ident=None):
    data = await index(sess)
    if ident is None:
        return {"artists": {"index": [{"name": "", "artist": [a for a, _ in data.values()]}]}}
    if ident not in data:
        raise HTTPException(404, "artist not found")
    artist, songs = data[ident]
    albums = []
    if not ident.startswith("credit-"):
        result = await nd.subsonic_request("getArtist", sess, [("id", ident)])
        albums = result.get("artist", {}).get("album", [])
    return {"artist": {**artist, "album": albums, "song": songs}}
