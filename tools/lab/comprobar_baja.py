"""Laboratorio: copia de baja calidad (96 kbit/s) para caminos lentos.

Canciones ficticias (4 min 20 s a 256 kbit/s con carátula grande; otra a 128 kbit/s), cuenta ficticia «ana»,
todo en 127.0.0.1 y en la caché propia del laboratorio. Comprueba: que la copia es AAC ~96 kbit/s sin carátula
y de la misma duración; rangos al azar coherentes; que rehecha tras borrarla sale idéntica byte a byte; que una
canción ya pequeña recibe su copia ligera; y cuánto tarda en llegar lo necesario para sonar con la ligera y con
la baja cuando la app ha medido un camino lento. Se borra al terminar.
"""
import json
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
LOW_DIR = lab.APP_DATA / "cache" / "armonia-baja"
folder = lab.MUSIC / "Baja"
folder.mkdir(exist_ok=True)
big, small = folder / "Pista lenta.m4a", folder / "Pista pequeña.m4a"
cover = folder / "portada.jpg"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "nullsrc=s=1000x1000,geq=random(1)*255:128:128",
                "-frames:v", "1", "-q:v", "2", str(cover)], check=True)
for target, kbps, title in ((big, "256k", "Pista lenta"), (small, "128k", "Pista pequeña")):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anoisesrc=d=260:c=pink:a=0.15",
                    "-f", "lavfi", "-i", "sine=f=220:d=260", "-i", str(cover),
                    "-filter_complex", "[0][1]amix=2,aformat=channel_layouts=stereo[a]", "-map", "[a]", "-map", "2:v",
                    "-c:a", "aac", "-b:a", kbps, "-c:v", "copy", "-disposition:v", "attached_pic", "-movflags", "+faststart",
                    "-metadata", f"title={title}", "-metadata", "artist=Baja", "-metadata", "album=Baja",
                    "-metadata", "albumartist=Baja", str(target)], check=True)
cover.unlink()
tmp = Path(tempfile.mkdtemp(prefix="baja-"))
try:
    lab.scan(full=True)
    songs = {s["title"]: s for s in lab.subsonic("search3", query="Pista", songCount=10, albumCount=0,
                                                   artistCount=0)["searchResult3"]["song"] if s["album"] == "Baja"}
    big_id, small_id = songs["Pista lenta"]["id"], songs["Pista pequeña"]["id"]
    session = httpx.post(f"{APP}/api/login", json={"username": lab.USER, "password": lab.PASSWORD},
                         timeout=30).json()["sessionId"]
    base = {"X-Session-Id": session}
    low_h = {**base, "X-Armonia-Variante": "baja", "X-Armonia-Ritmo": "400"}
    light_h = {**base, "X-Armonia-Variante": "ligera", "X-Armonia-Ritmo": "400"}

    def get(song_id, headers, fast=True):
        h = {**headers, "X-Armonia-Ritmo": "100000"} if fast else headers
        start = time.perf_counter()
        with httpx.Client(timeout=120, trust_env=False) as c:
            with c.stream("GET", f"{APP}/api/stream/{song_id}", headers=h) as r:
                first = None
                body = b""
                for chunk in r.iter_raw():
                    first = first or time.perf_counter() - start
                    body += chunk
                return r.status_code, dict(r.headers), body, first

    for f in LOW_DIR.glob("*.m4a") if LOW_DIR.exists() else ():
        f.unlink()
    status, headers, low, first = get(big_id, low_h)
    assert status == 200 and headers["x-armonia-variante"] == "baja", (status, headers.get("x-armonia-variante"))
    _, _, original, _ = get(big_id, {**base, "X-Armonia-Transfer": "download"})
    (tmp / "o.m4a").write_bytes(original)
    (tmp / "b.m4a").write_bytes(low)

    def probe(path):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,bit_rate:format=duration",
                              "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
        return json.loads(out)
    o, b = probe(tmp / "o.m4a"), probe(tmp / "b.m4a")
    errors = subprocess.run(["ffmpeg", "-v", "error", "-i", str(tmp / "b.m4a"), "-f", "null", "-"],
                            capture_output=True, text=True).stderr.strip()
    print(f"primera petición (hace la copia): primer byte a los {first * 1000:.0f} ms")
    print(f"original {len(original) / 1024:.0f} KB ({len(o['streams'])} pistas: "
          f"{', '.join(s['codec_type'] for s in o['streams'])}), {float(o['format']['duration']):.2f} s")
    print(f"baja     {len(low) / 1024:.0f} KB ({len(b['streams'])} pista: {b['streams'][0]['codec_name']} "
          f"{int(b['streams'][0]['bit_rate']) // 1000} kbit/s), {float(b['format']['duration']):.2f} s; "
          f"errores al decodificarla entera: {errors or 'ninguno'}")
    print(f"respuesta: variante={headers['x-armonia-variante']}  ritmo={headers['x-armonia-ritmo']}")

    _, _, again, first_cached = get(big_id, low_h)
    print(f"segunda petición (ya hecha): primer byte a los {first_cached * 1000:.0f} ms; mismos bytes: {'sí' if again == low else 'NO'}")

    random.seed(5)
    bad = 0
    with httpx.Client(timeout=120, trust_env=False) as c:
        for _ in range(25):
            a = random.randrange(len(low))
            z = min(len(low) - 1, a + random.randrange(1, 300_000))
            r = c.get(f"{APP}/api/stream/{big_id}", headers={**low_h, "X-Armonia-Ritmo": "100000", "Range": f"bytes={a}-{z}"})
            bad += r.status_code != 206 or r.content != low[a:z + 1] or r.headers["content-range"] != f"bytes {a}-{z}/{len(low)}"
    print(f"25 rangos al azar de la baja: {25 - bad} coinciden byte a byte con su posición")

    made = list(LOW_DIR.glob("*.m4a"))
    for f in made:
        f.unlink()
    _, _, remade, _ = get(big_id, low_h)
    print(f"borrada del disco ({len(made)} archivo) y hecha otra vez: idéntica byte a byte: {'sí' if remade == low else 'NO'}")

    _, h_small, small_low, _ = get(small_id, low_h)
    _, _, small_light, _ = get(small_id, light_h)
    print(f"canción a 128 kbit/s pedida en baja: variante={h_small['x-armonia-variante']}, "
          f"igual que su ligera: {'sí' if small_low == small_light else 'NO'}")

    def header_end(data):
        import struct
        pos = 0
        while True:
            n, t = struct.unpack(">I4s", data[pos:pos + 8])
            if t == b"mdat":
                return pos
            pos += n

    def time_to_start(headers, data, audio_kbps):
        need = header_end(data) + int(2.5 * audio_kbps * 1000 / 8)  # cabecera + 2,5 s de audio (lo que pide ExoPlayer)
        start = time.perf_counter()
        got = 0
        with httpx.Client(timeout=120, trust_env=False) as c:
            with c.stream("GET", f"{APP}/api/stream/{big_id}", headers=headers) as r:
                for chunk in r.iter_raw():
                    got += len(chunk)
                    if got >= need:
                        return time.perf_counter() - start, need
        return None, need

    _, _, light, _ = get(big_id, light_h)
    print("\nLo necesario para sonar (cabecera + 2,5 s de audio) con la app midiendo un camino de 400 kbit/s:")
    for label, h, data, kbps in (("ligera (256 kbit/s)", light_h, light, 256), ("baja (96 kbit/s, ya hecha)", low_h, low, 96)):
        secs, need = time_to_start(h, data, kbps)
        print(f"  {label:28} {need / 1024:5.0f} KB en {secs * 1000:6.0f} ms")
    print(f"  a ese ritmo sostenido la canción entera ocupa: ligera {len(light) / 1024:.0f} KB, baja {len(low) / 1024:.0f} KB")
finally:
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    for f in (big, small):
        f.unlink(missing_ok=True)
    folder.rmdir()
    for f in LOW_DIR.glob("*.m4a") if LOW_DIR.exists() else ():
        f.unlink()
    lab.scan(full=True)
