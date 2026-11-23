import asyncio

import pytest
from fastapi import HTTPException

from services import library_artists as artists


def test_legacy_credits_deduplicate_and_explicit_album_owner_wins():
    names = ["Nikone", "Hard GZ", "Lupita's Friends"]
    combined = ", ".join(names)
    listed = [{"id": n, "name": n} for n in [*names[:2], combined]]
    songs = [{"id": str(i), "artist": combined, "albumArtist": combined} for i in range(3)]
    songs.append({"id": "guest", "artist": combined, "albumArtist": "Nikone"})
    entries = {a["name"]: [s["id"] for s in rows] for a, rows in artists.artist_index(listed, songs).values()}
    assert entries == {n: ["0", "1", "2"] + (["guest"] if n == "Nikone" else []) for n in names}


def test_structured_credits_preserve_artist_names_with_punctuation():
    a = "Tyler, The Creator"
    credits = [{"name": a}, {"name": "Bea"}]
    joined = a + ", Bea"
    songs = [{"id": "1", "artist": joined, "artists": credits, "albumArtists": [{"name": joined}]},
             {"id": "2", "artist": a}]
    entries = {entry["name"]: [s["id"] for s in rows] for entry, rows in artists.artist_index([], songs).values()}
    assert entries == {a: ["1", "2"], "Bea": ["1"]}


def test_artist_cache_is_scoped_to_session_and_current_folders(monkeypatch):
    artists._cache.clear()
    grants = {"a": "one", "b": "two"}
    searches = []

    async def request(verb, session, pairs):
        folder = grants[session["id"]]
        if verb == "getMusicFolders":
            return {"musicFolders": {"musicFolder": [{"id": folder}]}}
        if verb == "getArtists":
            return {}
        assert verb == "search3"
        searches.append(folder)
        return {"searchResult3": {"song": [{"id": folder, "artist": folder}]}}

    monkeypatch.setattr(artists.nd, "subsonic_request", request)

    async def check():
        a, b = {"id": "a"}, {"id": "b"}
        ident = next(iter(await artists.index(a)))
        assert (await artists.browse(a, ident))["artist"]["song"][0]["id"] == "one"
        with pytest.raises(HTTPException):
            await artists.browse(b, ident)
        grants["a"] = "three"
        with pytest.raises(HTTPException):
            await artists.browse(a, ident)
        assert searches == ["one", "two", "three"]
    asyncio.run(check())
