"""Una canción nueva etiquetada con el código corregido, como la dejaría una importación (laboratorio)."""
import subprocess
import sys

import lab

sys.path.insert(0, str(lab.ROOT / "middleware"))
from services import tagger_service  # noqa: E402

def make():
    target = lab.MUSIC / "Lúa Norte, Bruma Clara" / "Lúa Norte, Bruma Clara - Marea viva.m4a"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=523:duration=24",
                    "-ac", "1", "-c:a", "aac", "-b:a", "48k", str(target)], check=True)
    tagger_service.tag(str(target), "Lúa Norte, Bruma Clara", "Marea viva", "Mareas", ["Lúa Norte", "Bruma Clara"])


if __name__ == "__main__":
    make()
    lab.scan()
    albums = lab.subsonic("getAlbumList2", type="alphabeticalByName", size=500)["albumList2"]["album"]
    print("álbumes:", sorted((a["name"], a["artist"], a["songCount"]) for a in albums if a["name"] == "Mareas"))
    song = next(s for s in lab.subsonic("search3", query="Marea viva", songCount=5)["searchResult3"]["song"])
    print("canción:", song["artist"], "| intérpretes:", [a["name"] for a in song.get("artists", [])], "| artista del álbum:", [a["name"] for a in song.get("albumArtists", [])])
    plays = [(s["title"], s.get("playCount")) for s in lab.subsonic("search3", query="", songCount=500)["searchResult3"]["song"] if s.get("playCount")]
    print("reproducciones registradas:", plays)
    print("índice de artistas:", sorted(a["name"] for g in lab.subsonic("getArtists")["artists"]["index"] for a in g["artist"]))
