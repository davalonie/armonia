"""Lab check: track number, disc and original date on some songs of an album must not split it in Navidrome."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "middleware"))
import lab  # noqa: E402
from mutagen import File as MutagenFile  # noqa: E402
from services import tagger_service  # noqa: E402


def albums():
    found = lab.subsonic("getAlbumList2", type="alphabeticalByName", size=500)["albumList2"].get("album", [])
    return {(a["artist"], a["name"]): a for a in found}


before = albums()
key = ("Lúa Norte", "Mareas")
ids_before = sorted(s["id"] for s in lab.subsonic("getAlbum", id=before[key]["id"])["album"]["song"])
files = []
for path in sorted((lab.LAB / "music").rglob("*.m4a")):
    tags = MutagenFile(str(path), easy=True)
    if (tags.get("album") or [""])[0] == "Mareas" and (tags.get("albumartist") or [""])[0] == "Lúa Norte":
        files.append((path, tags))
# Only some of them, and with two different dates: the case of an album imported in pieces.
for number, (path, tags) in enumerate(files[:5], start=1):
    names = tags.get("artists")
    tagger_service.tag(str(path), tags["artist"][0], tags["title"][0], "Mareas", names, "Lúa Norte",
                       details={"track": number, "disc": 1, "date": "2019-03-08" if number < 4 else "2019"})
lab.scan(full=True)
after = albums()
album = lab.subsonic("getAlbum", id=after[key]["id"])["album"]
songs = album["song"]
print("álbumes antes/después:", len(before), len(after))
print("«Mareas» de Lúa Norte: canciones", len(songs), "| mismo id de álbum:", before[key]["id"] == after[key]["id"])
print("mismos ids de canción:", sorted(s["id"] for s in songs) == ids_before)
by_year = lab.subsonic("getAlbumList2", type="byYear", fromYear=2019, toYear=2019, size=50)["albumList2"].get("album", [])
print("álbumes del año 2019:", [(a["artist"], a["name"]) for a in by_year])
print("orden por pista:", [(s.get("track"), s["title"]) for s in songs][:6])
print("año del álbum:", album.get("year"), "| años de canción:", sorted({s.get("year") for s in songs}, key=str))
assert len(before) == len(after) and sorted(s["id"] for s in songs) == ids_before and album.get("year") == 2019
