"""Private identifier hints, never a global name/artist resolver."""
import unicodedata
from uuid import UUID


def name_key(name):
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def remember(connection, user, track):
    identifiers = track.get("artist_mbids") or []
    if len(identifiers) != 1 or not track.get("artist"):
        return  # A multi-artist credit is not an unambiguous name -> ID mapping.
    try:
        ident = str(UUID(str(identifiers[0])))
    except (ValueError, TypeError):
        return
    connection.execute("INSERT OR IGNORE INTO artist_identities VALUES (?,?,?)", (user, name_key(track["artist"]), ident))


def supplement(connection, user, ranking):
    for entry in ranking.get("items", []):
        artist = entry.get("item", {})
        if artist.get("musicbrainz_id") or not artist.get("name"):
            continue
        ids = connection.execute("SELECT mbid FROM artist_identities WHERE owner=? AND name=? LIMIT 2",
            (user, name_key(artist["name"]))).fetchall()
        if len(ids) == 1:
            artist["musicbrainz_id"] = ids[0][0]
    return ranking
