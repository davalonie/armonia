"""Laboratorio: cuanto tarda en empezar a llegar una cancion directa de Navidrome frente a pasando por Armonia.

Mismo codigo que r14, mismo Navidrome 0.64.2, cuenta ficticia «ana» y seis canciones ficticias de
4 min 20 s a 128 kbps (unos 4,2 MB, como las reales). Todo en 127.0.0.1: la red no interviene, asi que
la diferencia es solo lo que añade Armonia.

«Fria» = el archivo se saca antes de la cache de disco del sistema (posix_fadvise DONTNEED), como una
cancion que no se ha tocado hace tiempo. Cada medicion abre una conexion nueva, como el primer toque.
"""
import hashlib
import os
import secrets
import statistics
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lab

APP = f"http://127.0.0.1:{lab.APP_PORT}"
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 10


def evict(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    finally:
        os.close(fd)


def timed(url, headers=None, params=None):
    """Seconds to the response headers, to the first audio byte and to the whole file, on a fresh connection."""
    start = time.perf_counter()
    with httpx.Client(timeout=30, trust_env=False) as client:
        with client.stream("GET", url, headers={"Range": "bytes=0-", **(headers or {})}, params=params) as response:
            head = time.perf_counter()
            assert response.status_code in (200, 206), response.status_code
            first = None
            size = 0
            for chunk in response.iter_raw():
                if first is None:
                    first = time.perf_counter()
                size += len(chunk)
    end = time.perf_counter()
    return (head - start) * 1000, (first - start) * 1000, (end - start) * 1000, size


def subsonic_params():
    salt = secrets.token_hex(6)
    token = hashlib.md5((lab.PASSWORD + salt).encode()).hexdigest()
    return {"u": lab.USER, "t": token, "s": salt, "v": "1.16.1", "c": "medicion"}


def ensure_songs():
    """The six fictitious songs; created and indexed only if missing (removed after each measurement)."""
    import subprocess
    folder = lab.MUSIC / "Medición"
    folder.mkdir(exist_ok=True)
    made = False
    for n in range(1, 7):
        target = folder / f"Pista larga {n}.m4a"
        if not target.exists():
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "anoisesrc=d=260:c=pink:a=0.3",
                            "-f", "lavfi", "-i", f"sine=f={200 + n * 40}:d=260", "-filter_complex", "amix=inputs=2",
                            "-c:a", "aac", "-b:a", "128k", "-metadata", f"title=Pista larga {n}", "-metadata", "artist=Medición",
                            "-metadata", "album=Medición", "-metadata", "albumartist=Medición", str(target)], check=True)
            made = True
    if made:
        lab.scan(full=True)


ensure_songs()
songs = [s for s in lab.subsonic("search3", query="Pista larga", songCount=20, albumCount=0, artistCount=0)["searchResult3"]["song"]
         if s["album"] == "Medición"]
assert len(songs) == 6, len(songs)
paths = {s["id"]: lab.MUSIC / "Medición" / f"{s['title']}.m4a" for s in songs}
session = httpx.post(f"{APP}/api/login", json={"username": lab.USER, "password": lab.PASSWORD}, timeout=30).json()["sessionId"]
armonia_headers = {"X-Session-Id": session}

results = {(way, temp): [] for way in ("directo", "armonia") for temp in ("fria", "caliente")}
for round_ in range(ROUNDS):
    for n, song in enumerate(songs):
        # Alternate who goes first so neither always gets the warm disk.
        order = ("directo", "armonia") if (round_ + n) % 2 == 0 else ("armonia", "directo")
        for way in order:
            for temp in ("fria", "caliente"):
                if temp == "fria":
                    evict(paths[song["id"]])
                if way == "directo":
                    sample = timed(f"{lab.ND}/rest/stream", params={"id": song["id"], **subsonic_params()})
                else:
                    sample = timed(f"{APP}/api/stream/{song['id']}", headers=armonia_headers)
                assert sample[3] > 4_000_000, sample
                results[(way, temp)].append(sample)

print(f"{ROUNDS * len(songs)} peticiones por caso, conexion nueva cada vez, todo local (sin red)\n")
print(f"{'camino':9} {'disco':9} {'cabeceras ms':>14} {'primer byte ms':>16} {'archivo entero ms':>19}")
for (way, temp), samples in results.items():
    def cell(i):
        values = sorted(s[i] for s in samples)
        return f"{statistics.median(values):7.1f} (p90 {values[int(len(values) * 0.9) - 1]:5.1f})"
    print(f"{way:9} {temp:9} {cell(0):>14} {cell(1):>16} {cell(2):>19}")
for temp in ("fria", "caliente"):
    extra = statistics.median(s[1] for s in results[("armonia", temp)]) - statistics.median(s[1] for s in results[("directo", temp)])
    print(f"\nArmonia añade al primer byte ({temp}): {extra:+.1f} ms")
