"""Laboratorio: un camino lento entre el emulador y el Armonia de laboratorio, con su velocidad y su retraso.

El emulador de esta version no aplica `network speed`/`network delay` (medido 19-11-2026: las canciones llegaban
al ritmo del propio servidor y el ping a 0,7 ms). Asi que la app habla con este intermediario (127.0.0.1:18480,
el puerto que ya usa) y el con Armonia (127.0.0.1:18481).

Un solo enlace compartido hacia el movil, como una conexion real: todo lo que va al movil hace cola en el y sale
a la velocidad elegida, y cada trozo llega ademas con el retraso de ida. La cola admite como mucho QUEUE_S
segundos de datos (como el bufer de un router o una antena); llena, deja de leer del servidor (TCP lo frena).
Hacia el servidor solo el retraso. Velocidad y retraso se leen de camino-lento.json en cada trozo:
    {"kbps": 400, "delay_ms": 60}      kbps 0 = sin limite
"""
import asyncio
import json
import time
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / "runtime/lab/camino-lento.json"
LISTEN, TARGET = 18480, 18481
QUEUE_S = 1.0
PIECE = 4096


def config():
    try:
        value = json.loads(CONFIG.read_text())
        return int(value.get("kbps", 0)), int(value.get("delay_ms", 0))
    except (OSError, ValueError):
        return 0, 0


class Link:
    """Bytes towards the phone, in arrival order, out at the chosen rate."""

    def __init__(self):
        self.queue = asyncio.Queue()
        self.queued = 0
        self.room = asyncio.Event()
        self.room.set()

    async def send(self, writer, data):
        kbps, _ = config()
        limit = max(int(kbps * 1000 / 8 * QUEUE_S), 32 * 1024) if kbps else 1 << 30
        while self.queued + len(data) > limit:
            self.room.clear()
            await self.room.wait()
        self.queued += len(data)
        await self.queue.put((writer, data, time.monotonic()))

    async def drain(self):
        free_at = time.monotonic()
        while True:
            writer, data, queued_at = await self.queue.get()
            kbps, delay = config()
            now = time.monotonic()
            free_at = max(free_at, now)
            if kbps:
                free_at += len(data) * 8 / (kbps * 1000)
            due = max(free_at, queued_at + delay / 1000)
            if due > now:
                await asyncio.sleep(due - now)
            self.queued -= len(data)
            self.room.set()
            if not data:  # the server finished this response: close after what was queued before it
                writer.close()
                continue
            if not writer.is_closing():
                writer.write(data)
                try:
                    await writer.drain()
                except ConnectionError:
                    pass


link = Link()


async def handle(phone_reader, phone_writer):
    try:
        server_reader, server_writer = await asyncio.open_connection("127.0.0.1", TARGET)
    except OSError:
        phone_writer.close()
        return

    async def up():
        try:
            while data := await phone_reader.read(65536):
                _, delay = config()
                if delay:
                    await asyncio.sleep(delay / 1000)
                server_writer.write(data)
                await server_writer.drain()
        except ConnectionError:
            pass
        finally:
            server_writer.close()

    async def down():
        try:
            while data := await server_reader.read(PIECE):
                await link.send(phone_writer, data)
        except ConnectionError:
            pass
        finally:
            await link.send(phone_writer, b"")  # closed after what is queued
    await asyncio.gather(up(), down())


async def main():
    asyncio.create_task(link.drain())
    server = await asyncio.start_server(handle, "127.0.0.1", LISTEN)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
