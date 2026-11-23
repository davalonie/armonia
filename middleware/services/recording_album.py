"""Resolve a single to an album edition using public recording metadata."""
import re
import unicodedata

import httpx


def folded(text):
    value = unicodedata.normalize("NFKD", text or "").casefold()
    return " ".join("".join(c for c in value if not unicodedata.combining(c)).split())


def single_title(album, title):
    value = re.sub(r"\s*[-–]\s*single$", "", folded(album))
    return value in {"", "singles", folded(title)}


def match(rows, title, artist, duration):
    if not duration or not title or not artist:
        return None
    # Match the whole credit, in order. A different remix, guest, or edition remains ambiguous.
    def credit(text):
        return re.sub(r"\s*(?:,| & )\s*", "|", folded(text))
    found = {}
    for row in rows:
        album = row.get("collectionName") or ""
        if row.get("wrapperType") != "track" or row.get("kind") != "song" or not album:
            continue
        if folded(row.get("trackName")) != folded(title) or credit(row.get("artistName")) != credit(artist):
            continue
        if abs((row.get("trackTimeMillis") or 0) / 1000 - duration) > 2:
            continue
        if (row.get("trackCount") or 0) < 2 or album.casefold().endswith(" - single"):
            continue
        key = (row.get("collectionId"), album)
        found[key] = {"album": album, "album_artist": row.get("collectionArtistName") or row.get("artistName"),
                      "track": row.get("trackNumber"), "disc": row.get("discNumber"),
                      "date": (row.get("releaseDate") or "")[:10], "evidence": row.get("trackViewUrl")}
    return next(iter(found.values())) if len(found) == 1 else None


def lookup(title, artist, duration):
    if not duration:
        return None
    # No service credentials, account identifiers, paths or listening history are sent.
    response = httpx.get("https://itunes.apple.com/search", params={"term": f"{title} {artist}",
                         "country": "ES", "entity": "song", "limit": 25}, timeout=4, trust_env=False)
    response.raise_for_status()
    return match(response.json().get("results", []), title, artist, duration)
