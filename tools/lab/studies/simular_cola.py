"""Laboratorio: un camino lento con cola (como el rele con poca cobertura, 18-11-2026 19:52) y un salto de cancion.

Un intermediario en 127.0.0.1 deja pasar hacia el «movil» 400 kbit/s por una sola cola compartida que nunca
descarta (lo que ya salio del servidor llega aunque el movil haya cerrado esa peticion, como los bytes en vuelo
del rele). Se pone la cancion A como lo hace el reproductor (leyendo todo lo que llega), a los 30 s se salta a la
cancion B y se mide cuando tiene B sus primeros 128 KB (cabecera + unos segundos: lo necesario para sonar).
Se compara el ritmo de la r19 (sostenido = la mitad de lo medido) con el nuevo (sostenido = 1,5x la cancion).
Canciones ficticias de 128 kbit/s con caratula, cuenta ficticia «ana». Se borra todo al terminar.
"""
import asyncio
import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))
import lab  # noqa: E402

APP_PORT, PROXY_PORT = 18482, 18483
PATH_BYTES_PER_S = 50_000  # 400 kbit/s, lo que llegaba al movil a las 19:53 (258-575 kbit/s)
SKIP_AT_S = 30
NEED = 128 * 1024

os.environ.update({"NAVIDROME_URL": lab.ND, "MUSIC_DIR": str(lab.MUSIC), "ARMONIA_DATA_DIR": str(lab.APP_DATA),
                   "MUSIC_CACHE_DIR": str(lab.APP_DATA / "cache"), "MUSIC_COOKIE_SECURE": "false",
                   "MUSIC_DELETE_USERS": "", "MUSIC_PUBLIC_ORIGIN": f"http://127.0.0.1:{APP_PORT}"})
os.chdir(lab.ROOT / "middleware")
import uvicorn  # noqa: E402

import server_app  # noqa: E402
from services import stream_pacing  # noqa: E402

server = uvicorn.Server(uvicorn.Config(server_app.app, host="127.0.0.1", port=APP_PORT, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
while not server.started:
    time.sleep(0.1)


class Bottleneck:
    """One queue for everything going to the phone, drained at the path's rate."""

    def __init__(self):
        self.queue = deque()
        self.queued = 0
        self.wake = asyncio.Event()

    async def drain(self):
        while True:
            if not self.queue:
                self.wake.clear()
                await self.wake.wait()
                continue
            writer, chunk = self.queue.popleft()
            self.queued -= len(chunk)
            await asyncio.sleep(len(chunk) / PATH_BYTES_PER_S)
            if not writer.is_closing():
                writer.write(chunk)

    async def handle(self, reader, writer):
        up_r, up_w = await asyncio.open_connection("127.0.0.1", APP_PORT)

        async def to_server():
            try:
                while data := await reader.read(65536):
                    up_w.write(data)
                    await up_w.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                up_w.close()

        async def to_phone():
            while data := await up_r.read(4096):
                self.queue.append((writer, data))
                self.queued += len(data)
                self.wake.set()
        await asyncio.gather(to_server(), to_phone(), return_exceptions=True)


async def scenario(song_a, song_b, session, label):
    neck = Bottleneck()
    drainer = asyncio.create_task(neck.drain())
    proxy = await asyncio.start_server(neck.handle, "127.0.0.1", PROXY_PORT)
    headers = f"X-Session-Id: {session}\r\nX-Armonia-Variante: ligera\r\nX-Armonia-Ritmo: 1000\r\n"

    async def request(song):
        r, w = await asyncio.open_connection("127.0.0.1", PROXY_PORT)
        w.write(f"GET /api/stream/{song} HTTP/1.1\r\nHost: lab\r\n{headers}Connection: close\r\n\r\n".encode())
        await w.drain()
        return r, w

    r, w = await request(song_a)
    start = time.perf_counter()
    got_a = 0
    while time.perf_counter() - start < SKIP_AT_S:
        try:
            data = await asyncio.wait_for(r.read(65536), timeout=SKIP_AT_S - (time.perf_counter() - start))
        except TimeoutError:
            break
        got_a += len(data)
    w.close()
    queued = neck.queued
    r, w = await request(song_b)
    skip = time.perf_counter()
    got, first, ready = 0, None, None
    while ready is None:
        data = await r.read(65536)
        if not data:
            break
        got += len(data)
        first = first or time.perf_counter() - skip
        if got >= NEED:
            ready = time.perf_counter() - skip
    w.close()
    print(f"{label:44} cola al saltar {queued / 1024:4.0f} KB; B: primer byte {first:4.1f} s, "
          f"lo necesario para sonar ({NEED // 1024} KB) {ready:4.1f} s; A recibio {got_a * 8 / SKIP_AT_S / 1000:.0f} kbit/s")
    proxy.close()
    drainer.cancel()


folder = lab.MUSIC / "Cola"
folder.mkdir(exist_ok=True)
cover = folder / "portada.jpg"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "nullsrc=s=800x800,geq=random(1)*255:128:128",
                "-frames:v", "1", "-q:v", "3", str(cover)], check=True)
files = []
for name in ("Cola A", "Cola B"):
    target = folder / f"{name}.m4a"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anoisesrc=d=240:c=pink:a=0.15", "-i", str(cover),
                    "-map", "0:a", "-map", "1:v", "-c:a", "aac", "-b:a", "128k", "-c:v", "copy", "-disposition:v", "attached_pic",
                    "-movflags", "+faststart", "-metadata", f"title={name}", "-metadata", "artist=Cola", "-metadata", "album=Cola",
                    "-metadata", "albumartist=Cola", str(target)], check=True)
    files.append(target)
cover.unlink()
try:
    import httpx
    lab.scan(full=True)
    ids = {s["title"]: s["id"] for s in lab.subsonic("search3", query="Cola", songCount=10, albumCount=0,
                                                        artistCount=0)["searchResult3"]["song"] if s["album"] == "Cola"}
    session = httpx.post(f"http://127.0.0.1:{APP_PORT}/api/login", json={"username": lab.USER, "password": lab.PASSWORD},
                         timeout=30).json()["sessionId"]
    print(f"camino de {PATH_BYTES_PER_S * 8 // 1000} kbit/s con cola compartida; cancion de 128 kbit/s; salto a los {SKIP_AT_S} s\n")
    for slow, label in ((0, "r19: sostenido = mitad de lo medido (500)"), (2000, "nuevo: sostenido = 1,5x la cancion (192)")):
        stream_pacing.SLOW_HINT_KBPS = slow
        asyncio.run(scenario(ids["Cola A"], ids["Cola B"], session, label))
finally:
    for f in files:
        f.unlink(missing_ok=True)
    folder.rmdir()
    lab.scan(full=True)
    server.should_exit = True
