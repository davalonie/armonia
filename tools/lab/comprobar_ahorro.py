"""Laboratorio: el servidor nuevo contra Navidrome de laboratorio (cuenta ficticia ana).

1. Carátulas: cabecera de caché y 304 con ETag.
2. Copia de ahorro (Opus 64): primera vez enviada mientras se hace (sin longitud), después completa y por rangos;
   tiempo hasta el primer byte y tamaño frente a la ligera.
3. «Baja» antigua: 503.
4. Preparar siguientes: hechas en segundo plano.
"""
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

APP = f"http://127.0.0.1:{lab.APP_PORT}"
session = httpx.post(f"{APP}/api/login", json={"username": lab.USER, "password": lab.PASSWORD}, timeout=30).json()["sessionId"]
H = {"X-Session-Id": session}
songs = sorted(lab.subsonic("search3", query="Tema", songCount=20, albumCount=0, artistCount=0)["searchResult3"]["song"],
               key=lambda s: s["title"])
c = httpx.Client(timeout=60, trust_env=False)

print("1. carátulas")
for cid in (songs[0]["coverArt"], songs[0]["albumId"] and lab.subsonic("getAlbum", id=songs[0]["albumId"])["album"]["coverArt"]):
    r = c.get(f"{APP}/api/library/getCoverArt", params={"id": cid, "size": 128}, headers=H)
    etag = r.headers.get("etag")
    r2 = c.get(f"{APP}/api/library/getCoverArt", params={"id": cid, "size": 128}, headers={**H, "If-None-Match": etag})
    print(f"   {cid[:3]}…: {r.status_code} {len(r.content)} B cache={r.headers.get('cache-control')!r}; "
          f"otra vez con ETag: {r2.status_code} {len(r2.content)} B cache={r2.headers.get('cache-control')!r}")

print("2. copia de ahorro")
for s in songs[:2]:
    t0 = time.perf_counter()
    first = None
    with c.stream("GET", f"{APP}/api/stream/{s['id']}", headers={**H, "X-Armonia-Variante": "ahorro", "X-Armonia-Ritmo": "16000"}) as r:
        size = 0
        for chunk in r.iter_raw():
            if first is None:
                first = time.perf_counter() - t0
            size += len(chunk)
        total = time.perf_counter() - t0
        print(f"   {s['title']} 1ª vez: {r.status_code} {r.headers.get('content-type')} longitud={r.headers.get('content-length')} "
              f"primer byte {first*1000:.0f} ms, {size/1e6:.2f} MB en {total:.1f} s")
    t0 = time.perf_counter()
    r = c.get(f"{APP}/api/stream/{s['id']}", headers={**H, "X-Armonia-Variante": "ahorro", "X-Armonia-Ritmo": "16000"})
    print(f"   {s['title']} 2ª vez: {r.status_code} longitud={r.headers.get('content-length')} ({len(r.content)/1e6:.2f} MB) en {time.perf_counter()-t0:.1f} s")
    part = c.get(f"{APP}/api/stream/{s['id']}", headers={**H, "X-Armonia-Variante": "ahorro", "Range": "bytes=1000-1999"})
    print(f"   rango: {part.status_code} {part.headers.get('content-range')} igual={part.content == r.content[1000:2000]}")
    light = c.get(f"{APP}/api/stream/{s['id']}", headers={**H, "X-Armonia-Variante": "ligera", "X-Armonia-Ritmo": "16000"})
    print(f"   ligera: {len(light.content)/1e6:.2f} MB (original {s['size']/1e6:.2f} MB, {s['duration']} s)")

print("3. baja antigua:", c.get(f"{APP}/api/stream/{songs[2]['id']}", headers={**H, "X-Armonia-Variante": "baja"}).status_code)

print("4. preparar")
ids = [songs[3]["id"], songs[4]["id"]]
r = c.post(f"{APP}/api/stream/preparar", json={"ids": ids}, headers=H)
print("   ", r.status_code, r.headers.get("x-armonia-preparadas"))
time.sleep(6)
folder = lab.APP_DATA / "cache" / "armonia-ahorro"
print("   copias en disco:", len(list(folder.glob("*.ogg"))), "->", sorted(round(p.stat().st_size / 1e6, 2) for p in folder.glob("*.ogg")))
t0 = time.perf_counter()
r = c.get(f"{APP}/api/stream/{songs[3]['id']}", headers={**H, "X-Armonia-Variante": "ahorro", "X-Armonia-Ritmo": "16000"})
print(f"   preparada: longitud={r.headers.get('content-length')} en {time.perf_counter()-t0:.2f} s")
