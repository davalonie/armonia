"""Qué conserva Navidrome 0.64.2 cuando cambia el artista de álbum de un archivo (solo laboratorio).

Toma una foto por la API (ids de canción, playlists, favoritas, reproducciones, álbumes),
aplica la reparación sobre la música ficticia, reescanea, vuelve a fotografiar y compara.
Después restaura con la copia y comprueba que todo vuelve al estado inicial.
"""
import json
import subprocess
import sys
from pathlib import Path

import lab

TOOL = [sys.executable, "-m", "tools.repair_album_artists", str(lab.MUSIC)]
CWD = lab.ROOT / "middleware"


def photo():
    songs = lab.subsonic("search3", query="", songCount=500, albumCount=0, artistCount=0)["searchResult3"]["song"]
    albums = lab.subsonic("getAlbumList2", type="alphabeticalByName", size=500)["albumList2"].get("album", [])
    playlists = {}
    for p in lab.subsonic("getPlaylists")["playlists"].get("playlist", []):
        playlists[p["name"]] = [e["id"] for e in lab.subsonic("getPlaylist", id=p["id"])["playlist"].get("entry", [])]
    starred = lab.subsonic("getStarred2")["starred2"]
    index = lab.subsonic("getArtists")["artists"].get("index", [])
    # La «ruta» de Subsonic es virtual (se compone con el artista de álbum) y cambia con la
    # reparación; la clave estable es lo que la reparación no toca: artista, álbum y título.
    def key(s):
        return " | ".join((s["artist"], s["album"], s["title"]))
    assert len({key(s) for s in songs}) == len(songs)
    return {
        "songs": {key(s): s["id"] for s in songs},
        "song_album": {key(s): (s["album"], s.get("albumId")) for s in songs},
        "display_artist": {key(s): s["artist"] for s in songs},
        "plays": {key(s): s.get("playCount", 0) for s in songs if s.get("playCount")},
        "albums": sorted((a["name"], a["artist"], a["songCount"]) for a in albums),
        "playlists": playlists,
        "starred_songs": sorted(s["id"] for s in starred.get("song", [])),
        "artists": sorted(a["name"] for group in index for a in group["artist"]),
    }


def same(before, after, key):
    return before[key] == after[key]


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else lab.LAB / "reparacion-resultado.json"
    backup = lab.LAB / "copia-etiquetas.json"
    backup.unlink(missing_ok=True)
    before = photo()
    subprocess.run([*TOOL, "--aplicar", "--copia", str(backup)], cwd=CWD, check=True, stdout=subprocess.DEVNULL)
    lab.scan()
    after = photo()
    subprocess.run([*TOOL, "--restaurar", str(backup)], cwd=CWD, check=True, stdout=subprocess.DEVNULL)
    lab.scan()
    restored = photo()
    moved = [p for p in before["songs"] if before["song_album"][p][1] != after["song_album"][p][1]]
    result = {
        "albumes_antes": before["albums"], "albumes_despues": after["albums"],
        "artistas_antes": before["artists"], "artistas_despues": after["artists"],
        "canciones_que_cambian_de_album": len(moved),
        "ids_de_cancion_conservados": same(before, after, "songs"),
        "ids_que_cambian": {p: [before["songs"][p], after["songs"].get(p)] for p in before["songs"] if before["songs"][p] != after["songs"].get(p)},
        "playlists_conservadas": same(before, after, "playlists"),
        "favoritas_conservadas": same(before, after, "starred_songs"),
        "reproducciones_conservadas": same(before, after, "plays"),
        "texto_de_artista_de_cada_cancion_conservado": same(before, after, "display_artist"),
        "restauracion_devuelve_el_estado_inicial": {k: same(before, restored, k) for k in before},
    }
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if not k.startswith(("albumes", "artistas"))}, ensure_ascii=False, indent=1))
    print("álbumes:", len(before["albums"]), "→", len(after["albums"]), "→ (restaurado)", len(restored["albums"]))
    print("artistas en el índice:", len(before["artists"]), "→", len(after["artists"]))
    for album in after["albums"]:
        print("  ", album)


if __name__ == "__main__":
    main()
