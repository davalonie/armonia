"""Laboratorio: copia ligera (sin carátula incrustada) y ritmo según lo que mide la app.

Canción ficticia de 4 min 20 s con una carátula grande incrustada, cuenta ficticia «ana», todo en 127.0.0.1.
Compara: original vs ligera (audio idéntico con ffmpeg, rangos al azar coherentes) y cuánto tarda en llegar
lo necesario para sonar con un camino rápido y con uno lento simulado por el ritmo que pide la app.
Se borra al terminar.
"""
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab

APP = f"http://127.0.0.1:{lab.APP_PORT}"
folder = lab.MUSIC / "Ligera"
folder.mkdir(exist_ok=True)
target = folder / "Pista ligera.m4a"
cover = folder / "portada.jpg"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "nullsrc=s=1000x1000,geq=random(1)*255:128:128",
                "-frames:v", "1", "-q:v", "2", str(cover)], check=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anoisesrc=d=260:c=pink:a=0.3", "-i", str(cover),
                "-map", "0:a", "-map", "1:v", "-c:a", "aac", "-b:a", "128k", "-c:v", "copy", "-disposition:v", "attached_pic",
                "-movflags", "+faststart", "-metadata", "title=Pista ligera", "-metadata", "artist=Ligera",
                "-metadata", "album=Ligera", "-metadata", "albumartist=Ligera", str(target)], check=True)
cover.unlink()
tmp = Path(tempfile.mkdtemp(prefix="ligera-"))
try:
    lab.scan(full=True)
    song = next(s for s in lab.subsonic("search3", query="Pista ligera", songCount=5, albumCount=0,
                                        artistCount=0)["searchResult3"]["song"] if s["album"] == "Ligera")
    session = httpx.post(f"{APP}/api/login", json={"username": lab.USER, "password": lab.PASSWORD},
                         timeout=30).json()["sessionId"]
    base = {"X-Session-Id": session}
    light_h = {**base, "X-Armonia-Variante": "ligera"}

    def get(headers):
        with httpx.Client(timeout=120, trust_env=False) as c:
            r = c.get(f"{APP}/api/stream/{song['id']}", headers=headers)
            assert r.status_code in (200, 206), r.status_code
            return r

    original = get({**base, "X-Armonia-Transfer": "download"}).content
    light = get({**light_h, "X-Armonia-Ritmo": "100000"}).content
    (tmp / "o.m4a").write_bytes(original)
    (tmp / "l.m4a").write_bytes(light)

    def md5(path, copy):
        args = ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a"] + (["-c", "copy"] if copy else []) + ["-f", "md5", "-"]
        p = subprocess.run(args, capture_output=True, text=True)
        return p.stdout.strip(), p.stderr.strip()

    same = md5(tmp / "o.m4a", True) == md5(tmp / "l.m4a", True) and md5(tmp / "o.m4a", False) == md5(tmp / "l.m4a", False)
    errors = md5(tmp / "l.m4a", False)[1]
    print(f"original {len(original) / 1024:.0f} KB, ligera {len(light) / 1024:.0f} KB (−{(len(original) - len(light)) / 1024:.0f} KB);"
          f" audio idéntico: {'sí' if same else 'NO'}; errores de ffmpeg: {errors or 'ninguno'}")
    random.seed(3)
    bad = 0
    for _ in range(25):
        a = random.randrange(len(light))
        b = min(len(light) - 1, a + random.randrange(1, 400_000))
        r = get({**light_h, "Range": f"bytes={a}-{b}", "X-Armonia-Ritmo": "100000"})
        bad += r.content != light[a:b + 1] or r.headers["content-range"] != f"bytes {a}-{b}/{len(light)}"
    print(f"25 rangos al azar de la ligera: {25 - bad} coinciden byte a byte con su posición")

    def header_end(data):
        import struct
        pos = 0
        while True:
            n, t = struct.unpack(">I4s", data[pos:pos + 8])
            if t == b"mdat":
                return pos
            pos += n

    def time_to_start(headers, data):
        need = header_end(data) + 96 * 1024
        start = time.perf_counter()
        got = 0
        with httpx.Client(timeout=120, trust_env=False) as c:
            with c.stream("GET", f"{APP}/api/stream/{song['id']}", headers=headers) as r:
                rate = r.headers.get("x-armonia-ritmo")
                for chunk in r.iter_raw():
                    got += len(chunk)
                    if got >= need:
                        return time.perf_counter() - start, need, rate
        return None, need, rate

    print("\nLo necesario para sonar (cabecera + 96 KB) llega en:")
    for label, headers, data in (
            ("original, app actual (sin medida)", base, original),
            ("ligera, camino rápido (50 Mbit/s)", {**light_h, "X-Armonia-Ritmo": "50000"}, light),
            ("original, camino de ~1 Mbit/s", {**base, "X-Armonia-Ritmo": "1000"}, original),
            ("ligera, camino de ~1 Mbit/s", {**light_h, "X-Armonia-Ritmo": "1000"}, light)):
        secs, need, rate = time_to_start(headers, data)
        print(f"  {label:36} {need / 1024:5.0f} KB en {secs * 1000:6.0f} ms   ({rate})")
finally:
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    target.unlink(missing_ok=True)
    folder.rmdir()
    lab.scan(full=True)
