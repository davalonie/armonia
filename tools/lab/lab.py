"""Laboratorio aislado para la revision de interfaz: Navidrome 0.64.2 propio + Armonia real.

Todo es ficticio (nombres, portadas, tonos generados con ffmpeg). Solo escucha en 127.0.0.1,
usa contenedor, datos y puertos propios y no comparte nada con la instalacion en uso.

    python lab.py fixtures     # genera la musica de prueba (etiquetada como lo hacia la importacion)
    python lab.py up           # arranca Navidrome de laboratorio y crea la usuaria «ana»
    python lab.py seed         # playlist, favoritas y reproducciones de referencia
    python lab.py server       # Armonia (uvicorn) contra ese Navidrome, en primer plano
    python lab.py down         # para y borra el contenedor de laboratorio
"""
import hashlib
import json
import os
import secrets
import tempfile
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[1]
LAB = ROOT / "runtime/lab"
LAB.mkdir(mode=0o700, parents=True, exist_ok=True)
MUSIC, ND_DATA, APP_DATA = LAB / "music", LAB / "navidrome-data", LAB / "armonia-data"
DOCKER = ["docker", "--config", os.environ.get("DOCKER_CONFIG", str(ROOT / "runtime/docker-config"))]
CONTAINER, ND_PORT, APP_PORT = "armonia-lab-navidrome", 14533, 18480
def lab_password():
    path = LAB / "navidrome.password"
    if not path.exists():
        # El enlace solo se crea cuando la contraseña ya esta escrita por completo.
        with tempfile.NamedTemporaryFile(mode="w", dir=LAB) as temp:
            temp.write(secrets.token_urlsafe(32))
            temp.flush()
            try:
                os.link(temp.name, path)
            except FileExistsError:
                pass
    return path.read_text()


USER = "ana"
PASSWORD = lab_password()
ND = f"http://127.0.0.1:{ND_PORT}"

# (artista de album real, album, [(titulo, [interpretes])]) — etiquetado «antiguo»: ALBUMARTIST = todos.
CATALOG = [
    ("Lúa Norte", "Mareas", [("Bajamar", ["Lúa Norte"]), ("Luz de enero", ["Lúa Norte"]), ("Mapa sin nombre", ["Lúa Norte"]),
                             ("Cristal", ["Lúa Norte"]), ("Últimas farolas", ["Lúa Norte"]),
                             ("Volver despacio", ["Lúa Norte", "Vera Solano"]), ("La casa abierta", ["Lúa Norte", "Faro Sur"]),
                             ("Tierra adentro", ["Lúa Norte", "Vera Solano", "Faro Sur"])]),
    ("Lúa Norte", "Mareas (En directo)", [("Bajamar", ["Lúa Norte"]), ("Cristal", ["Lúa Norte"]), ("Luz de enero", ["Lúa Norte"])]),
    ("Otro Grupo", "Mareas", [("Pleamar", ["Otro Grupo"]), ("Espuma", ["Otro Grupo"])]),
    ("Faro Sur", "Invierno en casa", [("Estufa", ["Faro Sur"]), ("Ventana al patio", ["Faro Sur"]), ("Lana", ["Faro Sur"]),
                                      ("Domingo lento", ["Faro Sur"]), ("Antes del ruido", ["Faro Sur", "Bruma Clara"])]),
    ("Vera Solano", "Postales", [("Lisboa", ["Vera Solano"]), ("Oporto", ["Vera Solano"]), ("Cádiz", ["Vera Solano"]), ("Vigo", ["Vera Solano"])]),
    ("Niebla y Sal", "Sal", [("Salinas", ["Niebla y Sal"]), ("Marisma", ["Niebla y Sal"]), ("Garza", ["Niebla y Sal"]), ("Estero", ["Niebla y Sal"])]),
    ("Trío Uno, Dos & Tres", "Primer acto", [("Obertura", ["Trío Uno, Dos & Tres"]), ("Entreacto", ["Trío Uno, Dos & Tres"]), ("Telón", ["Trío Uno, Dos & Tres"])]),
    ("Camino Lento", "Singles", [("Kilómetro cero", ["Camino Lento"]), ("Arcén", ["Camino Lento"]), ("Peaje", ["Camino Lento"])]),
    ("Bruma Clara", "Singles", [("Amanece tarde", ["Bruma Clara"]), ("Rocío", ["Bruma Clara"]), ("Cuesta arriba", ["Bruma Clara", "Camino Lento"])]),
]


def safe(text):
    return "".join("_" if c in '/\\:*?"<>|' else c for c in text)


def fixtures():
    from mutagen.mp4 import MP4, MP4Cover

    MUSIC.mkdir(parents=True, exist_ok=True)
    count = 0
    for owner, album, songs in CATALOG:
        seed = int(hashlib.sha256((owner + album).encode()).hexdigest()[:12], 16)
        colors = ["#%06x" % ((seed >> shift) & 0xFFFFFF) for shift in (0, 24)]
        cover = LAB / "covers" / (safe(owner + " - " + album) + ".jpg")
        cover.parent.mkdir(exist_ok=True)
        if not cover.exists():
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                            f"gradients=s=640x640:c0={colors[0]}:c1={colors[1]}:x0=0:y0=0:x1=640:y1=640:d=1",
                            "-frames:v", "1", str(cover)], check=True)
        for index, (title, artists) in enumerate(songs):
            text = ", ".join(artists)
            # The same layout the importer publishes: <artista>/<artista - titulo>.m4a
            target = MUSIC / safe(text) / (safe(f"{text} - {title}") + (" (directo)" if "directo" in album else "") + ".m4a")
            count += 1
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                            f"sine=frequency={220 + 37 * ((seed + index) % 17)}:duration=24", "-ac", "1", "-c:a", "aac", "-b:a", "48k",
                            str(target)], check=True)
            audio = MP4(str(target))
            # Como lo escribia la importacion antes de la correccion: artista de album = texto completo.
            audio["\xa9ART"], audio["\xa9nam"], audio["\xa9alb"], audio["aART"] = text, title, album, text
            audio["covr"] = [MP4Cover(cover.read_bytes(), imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()
    print(f"{count} canciones ficticias en {MUSIC}")


def http(url, data=None, headers=None, method=None):
    request = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Content-Type": "application/json", **(headers or {})}, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"{}")


def subsonic(path, **params):
    query = urllib.parse.urlencode({"u": USER, "p": PASSWORD, "v": "1.16.1", "c": "lab", "f": "json", **params}, doseq=True)
    return http(f"{ND}/rest/{path}?{query}")["subsonic-response"]


def scan(full=False):
    subsonic("startScan", fullScan="true" if full else "false")
    for _ in range(120):
        time.sleep(1)
        if not subsonic("getScanStatus")["scanStatus"]["scanning"]:
            return
    raise SystemExit("el escaneo no termina")


def up():
    MUSIC.mkdir(exist_ok=True)
    ND_DATA.mkdir(exist_ok=True)
    subprocess.run([*DOCKER, "run", "-d", "--name", CONTAINER, "--label", "io.github.davalonie.armonia.lab=true", "--log-driver", "none", "--user", f"{os.getuid()}:{os.getgid()}",
                    "-p", f"127.0.0.1:{ND_PORT}:4533", "-v", f"{MUSIC}:{MUSIC}:ro", "-v", f"{ND_DATA}:/data",
                    "-e", f"ND_MUSICFOLDER={MUSIC}", "-e", "ND_DATAFOLDER=/data", "-e", "ND_LOGLEVEL=warn",
                    "-e", "ND_LASTFM_ENABLED=false", "-e", "ND_LISTENBRAINZ_ENABLED=false", "-e", "ND_ENABLEEXTERNALSERVICES=false",
                    "-e", "ND_ENABLESHARING=false", "-e", "ND_SEARCH_BACKEND=legacy", "-e", "ND_ENABLEINSIGHTSCOLLECTOR=false",
                    "--memory", "384m", "deluan/navidrome:0.64.2"], check=True, stdout=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{ND}/ping", timeout=2)
            break
        except OSError:
            time.sleep(1)
    try:
        http(f"{ND}/auth/createAdmin", {"username": USER, "password": PASSWORD})
    except urllib.error.HTTPError:
        pass  # ya existia
    scan(full=True)
    print("Navidrome de laboratorio listo:", len(subsonic("getAlbumList2", type="alphabeticalByName", size=500)["albumList2"].get("album", [])), "albumes")


def seed():
    songs = subsonic("search3", query="", songCount=500, albumCount=0, artistCount=0)["searchResult3"]["song"]
    by_title = {(s["title"], s["album"], s["artist"]): s["id"] for s in songs}
    pick = [ident for (title, album, artist), ident in sorted(by_title.items()) if album == "Mareas" and artist.startswith("Lúa Norte")]
    pick += [ident for (title, album, artist), ident in sorted(by_title.items()) if album in ("Postales", "Sal")]
    existing = {p["name"] for p in subsonic("getPlaylists")["playlists"].get("playlist", [])}
    if "Para conducir de noche" not in existing:
        subsonic("createPlaylist", name="Para conducir de noche", songId=pick)
    if "Domingo" not in existing:
        subsonic("createPlaylist", name="Domingo", songId=[i for (t, a, r), i in sorted(by_title.items()) if a in ("Invierno en casa", "Singles")])
    collaborations = [ident for (title, album, artist), ident in by_title.items() if "," in artist and "Trío" not in artist]
    subsonic("star", id=collaborations)
    for ident in collaborations[:2]:
        subsonic("scrobble", id=ident, submission="true")
    print("playlists, favoritas y reproducciones de referencia creadas")


def server():
    APP_DATA.mkdir(exist_ok=True)
    env = {**os.environ, "NAVIDROME_URL": ND, "MUSIC_DIR": str(MUSIC), "ARMONIA_DATA_DIR": str(APP_DATA),
           "MUSIC_CACHE_DIR": str(APP_DATA / "cache"), "MUSIC_COOKIE_SECURE": "false", "MUSIC_DELETE_USERS": "",
           "MUSIC_PUBLIC_ORIGIN": f"http://127.0.0.1:{APP_PORT}"}
    python = sys.executable
    os.chdir(ROOT / "middleware")  # main.py sirve frontend/dist relativo a su carpeta
    os.execve(python, [python, "-m", "uvicorn", "server_app:app", "--host", "127.0.0.1", "--port", str(APP_PORT), "--no-access-log", "--app-dir", str(SCRIPTS)],
              env)


def down():
    names = subprocess.check_output([*DOCKER, "ps", "-a", "--filter",
                                     "label=io.github.davalonie.armonia.lab=true", "--format", "{{.Names}}"], text=True).splitlines()
    if CONTAINER in names:
        subprocess.run([*DOCKER, "rm", "-f", CONTAINER], check=True)


if __name__ == "__main__":
    {"fixtures": fixtures, "up": up, "seed": seed, "server": server, "down": down}[sys.argv[1]]()
