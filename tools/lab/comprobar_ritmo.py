"""Laboratorio: Armonia entrega el principio de la canción al momento y el resto a ritmo; las descargas, enteras.

Una canción ficticia de 4 min 20 s a 128 kbps (unos 4,2 MB), cuenta ficticia «ana», todo en 127.0.0.1.
Se borra al terminar.
"""
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab

APP = f"http://127.0.0.1:{lab.APP_PORT}"
folder = lab.MUSIC / "Ritmo"
folder.mkdir(exist_ok=True)
target = folder / "Pista ritmo.m4a"
# Con carátula incrustada grande, como las canciones reales (cabecera de ~480 KB antes del audio).
cover = folder / "portada.jpg"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "nullsrc=s=1000x1000,geq=random(1)*255:128:128",
                "-frames:v", "1", "-q:v", "2", str(cover)], check=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anoisesrc=d=260:c=pink:a=0.3", "-i", str(cover),
                "-map", "0:a", "-map", "1:v", "-c:a", "aac", "-b:a", "128k", "-c:v", "copy", "-disposition:v", "attached_pic",
                "-movflags", "+faststart", "-metadata", "title=Pista ritmo", "-metadata", "artist=Ritmo",
                "-metadata", "album=Ritmo", "-metadata", "albumartist=Ritmo", str(target)], check=True)
cover.unlink()
import struct
with open(target, "rb") as h:
    pos = 0
    while True:
        h.seek(pos); size, kind = struct.unpack(">I4s", h.read(8))
        if kind == b"mdat":
            break
        pos += size
print(f"cabecera antes del audio: {pos / 1024:.0f} KB")
try:
    lab.scan(full=True)
    song = next(s for s in lab.subsonic("search3", query="Pista ritmo", songCount=5, albumCount=0,
                                        artistCount=0)["searchResult3"]["song"] if s["album"] == "Ritmo")
    session = httpx.post(f"{APP}/api/login", json={"username": lab.USER, "password": lab.PASSWORD},
                         timeout=30).json()["sessionId"]

    HEADER = pos + 96 * 1024

    def fetch(extra=None, offset=0):
        marks = {}
        start = time.perf_counter()
        size = 0
        with httpx.Client(timeout=60, trust_env=False) as client:
            with client.stream("GET", f"{APP}/api/stream/{song['id']}",
                               headers={"X-Session-Id": session, "Range": f"bytes={offset}-", **(extra or {})}) as r:
                assert r.status_code in (200, 206), r.status_code
                for chunk in r.iter_raw():
                    size += len(chunk)
                    for mark in (64 * 1024, 128 * 1024, 512 * 1024, 1024 * 1024, HEADER - offset):
                        if size >= mark and mark not in marks:
                            marks[mark] = time.perf_counter() - start
        return size, marks, time.perf_counter() - start

    for label, extra in (("reproducción", None), ("descarga sin conexión", {"X-Armonia-Transfer": "download"})):
        size, marks, total = fetch(extra)
        print(f"{label:22} {size / 1e6:.2f} MB  cabecera+96 KB en {marks[HEADER] * 1000:5.0f} ms  64 KB en {marks[65536] * 1000:5.0f} ms"
              f"  512 KB en {marks[524288]:5.2f} s  1 MB en {marks[1048576]:5.2f} s  entera en {total:5.2f} s")
    resumed = 207 * 1024
    size, marks, total = fetch(offset=resumed)
    print(f"reanudada desde 207 KB  {size / 1e6:.2f} MB  resto de cabecera+96 KB en {marks[HEADER - resumed] * 1000:5.0f} ms"
          f"  (antes de este arreglo: ~{(HEADER - resumed - 131072) / 256_000 * 1000:.0f} ms)  entera en {total:5.2f} s")
    rate = HEADER / 2_000_000 + (size - HEADER) * 8 / 1000 / 2048
    print(f"\nArranque (cabecera + 96 KB) a ~2 MB/s y el resto a 2048 kbit/s: canción entera en ~{rate:.1f} s;"
          f" dura 260 s, así que llega {260 / rate:.0f} veces más rápido de lo que suena.")
finally:
    target.unlink(missing_ok=True)
    folder.rmdir()
    lab.scan(full=True)
