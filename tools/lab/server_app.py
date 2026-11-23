"""Armonia real con los proveedores externos simulados (solo laboratorio).

Cualquier enlace de playlist devuelve una lista ficticia y las búsquedas externas devuelven
candidatos ficticios: no se contacta con Spotify ni con YouTube.
"""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "middleware"))

from main import app  # noqa: E402,F401
from routes import import_playlist  # noqa: E402
from services import spotify_client, ytdlp_service  # noqa: E402

TRACKS = [("Bajamar", ["Lúa Norte"], "Mareas"), ("Lisboa", ["Vera Solano"], "Postales"),
          ("Faros apagados", ["Costa Brava Trío"], "Litoral"), ("Niebla baja", ["Marea Baja", "Rumbo Fijo"], "Litoral"),
          ("Canción sin fuente", ["Nadie Conocido"], ""), ("Último tren", ["Telmo Arce Quinteto"], "Andenes")]


def vid(text):
    return hashlib.sha256(text.encode()).hexdigest()[:11]


async def fetch_playlist(url):
    tracks = [{"title": t, "artist": ", ".join(a), "artists": a, "album_artist": a[0], "album": album, "duration": 200.0 + 7 * i,
               "source_position": i, "source_id": f"spotify:track:lab{i}", "isrc": None, "source_unavailable": False}
              for i, (t, a, album) in enumerate(TRACKS)]
    return spotify_client._result("Lista de laboratorio", tracks, len(tracks), "embed", None)


def search(query, limit=10, source="youtube_music"):
    found = []
    for i, (title, artists, _album) in enumerate(TRACKS[2:]):
        if title.casefold() not in query.casefold() or "sin fuente" in title:
            continue
        name = ", ".join(artists)
        # Dos grabaciones compatibles: la app debe pedir que elija quien importa.
        found += [{"videoId": vid(title + "a"), "title": title, "channel": name, "duration": 214 + 7 * i, "album": ""},
                  {"videoId": vid(title + "b"), "title": f"{title} (En directo)", "channel": name, "duration": 251 + 7 * i, "album": ""},
                  {"videoId": vid(title + "c"), "title": title, "channel": name + " - Tema", "duration": 215 + 7 * i, "album": ""}]
    return found[:limit]


spotify_client.fetch_playlist = fetch_playlist
import_playlist.spotify_client.fetch_playlist = fetch_playlist
ytdlp_service.search = search
ytdlp_service.search_artists = lambda *a, **k: []

if __import__("os").environ.get("ARMONIA_LAB_CARATULAS_ANTES") == "1":
    # Como el servidor en uso (r20): ninguna carátula se puede guardar en el móvil (private, no-store).
    import main  # noqa: E402
    main._cacheable_cover = lambda request, response: False

if __import__("os").environ.get("ARMONIA_LAB_DESCARGAS") in ("1", "fallo"):
    # «Descargar y guardar» sin YouTube: una pista del laboratorio hace de audio descargado. El trabajo de
    # descarga, el etiquetado, la publicación en la biblioteca y el escaneo de Navidrome son los reales.
    import shutil  # noqa: E402
    import time  # noqa: E402

    FIXTURE = ROOT / "runtime/lab/music/Bruma Clara/Bruma Clara - Rocío.m4a"  # 24 s

    def _download_staged(video_id, artist, title, source="youtube", cancel_check=None, music_dir=None):
        time.sleep(4)  # como una descarga corta
        if __import__("os").environ.get("ARMONIA_LAB_DESCARGAS") == "fallo":
            from yt_dlp.utils import DownloadError
            raise DownloadError("fallo simulado del proveedor")
        target = Path(music_dir) / f"{ytdlp_service._sanitize(f'{artist} - {title}')}.m4a"
        shutil.copyfile(FIXTURE, target)
        return str(target), {}

    ytdlp_service._download_staged = _download_staged

    # Escuchar una canción de «Hecho para ti» que no está en la biblioteca, también sin YouTube: su audio sale del
    # búfer de memoria del servidor (el mismo que usa para lo ya preparado), relleno con la pista del laboratorio.
    from services import stream_buffer  # noqa: E402

    LAB_PREVIEWS = {"LabFaroEnc1", "LabFaroNie1"}
    _buffer_get = stream_buffer.get

    def _lab_buffer_get(owner, ident):
        if ident in LAB_PREVIEWS and (owner, ident) not in stream_buffer._songs:
            data = FIXTURE.read_bytes()
            stream_buffer._songs[owner, ident] = stream_buffer.Song(total=len(data), content_type="audio/mp4", data=bytearray(data))
        return _buffer_get(owner, ident)

    stream_buffer.get = _lab_buffer_get
