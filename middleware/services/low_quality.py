"""Data-saving copy of a song: Opus at 64 kbit/s in MP4, without the embedded cover, made with ffmpeg when the
app asks for it and kept on disk only for a while.

The app asks for it when the listener saves data (Settings: "Ahorro de datos", on mobile data or always) and
on any bad connection (PathRate.kt, Variants.kt); otherwise it plays the original (or its light copy).
Measured 18-11-2026 on the server with five songs from the library (AAC 128 kbit/s, 160-269 s): the copy is
1.45-2.32 MB against 2.9-4.8 MB, and making it takes 0.7-1.7 s depending on the encoder effort (1.1 s for a
161 s song at the effort used here; 1.6 s for 270 s). So nothing is converted in advance: a copy is made when
it is first asked for (or when the app asks for the next songs of its queue), kept for the next time, and
removed after four days without use or when the copies pass 500 MB (the listener's choice, 18-11-2026: never a
second copy of the whole library).

A copy is only sent complete. Sent while being made (tried in the lab, 18-11-2026) its length is unknown, and
the player then shows no duration and cannot seek within that song; waiting for it costs about 1.5 s, once.
In MP4 with its index first and 60 ms frames (index 19 KB for 270 s; 55 KB with 20 ms frames): in Ogg the
player had to read the end of the file to learn the duration, two more requests and ~150 KB read twice.

The output is repeatable byte for byte (bitexact flags, no tags), so a copy removed from disk and made again
is the same file the phone may already keep a piece of. A different encoding (options, encoder version) must be
a new variant name in the app and here, never the same one.
"""

import asyncio
import hashlib
import os
import shutil
import time
import uuid
from pathlib import Path

LOW_KBPS = 64
VERSION = "m1"
SUFFIX = ".m4a"
CONTENT_TYPE = "audio/mp4"
# Its own folder inside Armonía's cache (homelab/audio_cache.py only touches its own files at the top level).
DIR = Path(os.getenv("ARMONIA_LOW_DIR") or Path(os.getenv("MUSIC_CACHE_DIR") or "/app/cache") / "armonia-ahorro")
MAX_BYTES = int(os.getenv("ARMONIA_LOW_MAX_MB", "500")) * 1024 * 1024
MAX_AGE_SECONDS = int(float(os.getenv("ARMONIA_LOW_MAX_DAYS", "4")) * 86400)
MIN_FREE_BYTES = int(os.getenv("ARMONIA_LOW_MIN_FREE_MB", "2048")) * 1024 * 1024
MAX_SOURCE_BYTES = 300 * 1024 * 1024
TRANSCODE_SECONDS = 60
# Encoder effort 5 of 10: 1.1 s instead of 1.65 s for a 161 s song (18-11-2026), same size within 4 %.
COMMAND = ["ffmpeg", "-nostdin", "-v", "error", "-i", "{src}", "-map", "0:a:0", "-map_metadata", "-1",
           "-map_chapters", "-1", "-c:a", "libopus", "-b:a", f"{LOW_KBPS}k", "-vbr", "on",
           "-compression_level", "5", "-frame_duration", "60", "-application", "audio",
           "-fflags", "+bitexact", "-flags:a", "+bitexact", "-movflags", "+faststart", "-f", "mp4", "-y", "{dst}"]


class LowUnavailable(Exception):
    """No copy this time (disk, source or ffmpeg): the app falls back to another variant."""


def applicable(song: dict) -> bool:
    size, duration = song.get("size"), song.get("duration")
    return (isinstance(size, int) and 0 < size <= MAX_SOURCE_BYTES
            and isinstance(duration, int | float) and duration > 0)


def _lower_priority():
    os.nice(10)  # Behind everything else on the server: Navidrome, the web, other services.


async def transcode(src: Path, dst: Path, background: bool = False) -> None:
    """[background]: a copy made ahead of time goes behind everything else on the server. A copy someone is
    waiting for keeps the normal priority: measured 19-11-2026 in the lab with the machine busy (load 5 on 8
    cores), a 238 s song took 5.1 s at the lower priority, against 1.6 s for 270 s when the machine was idle."""
    command = [part.format(src=src, dst=dst) for part in COMMAND]
    process = await asyncio.create_subprocess_exec(
        *command, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE, preexec_fn=_lower_priority if background else None)
    try:
        await asyncio.wait_for(process.communicate(), TRANSCODE_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise LowUnavailable("ffmpeg took too long") from None
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    if process.returncode != 0:
        raise LowUnavailable("ffmpeg could not convert the song")


class LowStore:
    """Copies on disk, least recently used evicted first and none kept past [max_age] without use. One build
    per song at a time; a build goes on when the request that started it goes away, so the next request finds
    it ready. Songs someone is waiting for have their own slots, so preparing the next songs of a queue never
    delays the one that was just chosen."""

    def __init__(self, directory: Path = DIR, max_bytes: int = MAX_BYTES, min_free: int = MIN_FREE_BYTES,
                 convert=transcode, slots: int = 2, ahead_slots: int = 1, max_age: int = MAX_AGE_SECONDS,
                 clock=time.time):
        self.dir = Path(directory)
        self.max_bytes = max_bytes
        self.min_free = min_free
        self.max_age = max_age
        self.convert = convert
        self.clock = clock
        self._slots = asyncio.Semaphore(slots)
        self._ahead = asyncio.Semaphore(ahead_slots)
        self._building: dict[str, asyncio.Task] = {}
        self._swept = False

    def path_for(self, track_id: str, size: int) -> Path:
        digest = hashlib.sha256(f"{track_id}\0{size}".encode()).hexdigest()[:24]
        return self.dir / f"{digest}-{LOW_KBPS}k-{VERSION}{SUFFIX}"

    def ready(self, track_id: str, size: int) -> Path | None:
        path = self.path_for(track_id, size)
        if not path.exists():
            return None
        try:
            os.utime(path)
        except FileNotFoundError:
            return None
        return path

    def _start(self, track_id: str, size: int, fetch, ahead: bool) -> asyncio.Task:
        path = self.path_for(track_id, size)
        task = self._building.get(path.name)
        if task is None:
            task = asyncio.ensure_future(self._build(path, size, fetch, ahead))
            self._building[path.name] = task
            task.add_done_callback(lambda _: self._building.pop(path.name, None))
            task.add_done_callback(lambda t: t.cancelled() or t.exception())  # seen: maybe nobody waits for it
        return task

    async def get(self, track_id: str, size: int, fetch, ahead: bool = False) -> Path:
        """The copy's path; [fetch](dest) writes the original song to dest when it must be made."""
        if (path := self.ready(track_id, size)) is not None:
            return path
        return await asyncio.shield(self._start(track_id, size, fetch, ahead))

    def prepare(self, track_id: str, size: int, fetch) -> None:
        """Make the copy in the background, behind anything someone is waiting for."""
        if self.ready(track_id, size) is None:
            self._start(track_id, size, fetch, ahead=True)

    async def _build(self, path: Path, size: int, fetch, ahead: bool) -> Path:
        token = uuid.uuid4().hex
        src, out = self.dir / f".in-{token}", self.dir / f".out-{token}{SUFFIX}"
        if ahead:
            await self._ahead.acquire()
        try:
            async with self._slots:
                if path.exists():
                    return path
                self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
                self.sweep()
                # The original and the copy on disk while it is made; the copy is well under half the original.
                self._make_room(disk=2 * size, budget=size // 2, keep=None)
                try:
                    await fetch(src)
                    await self.convert(src, out, background=ahead)
                    if not out.exists() or out.stat().st_size == 0:
                        raise LowUnavailable("ffmpeg wrote nothing")
                    os.replace(out, path)
                finally:
                    src.unlink(missing_ok=True)
                    out.unlink(missing_ok=True)
        finally:
            if ahead:
                self._ahead.release()
        self._make_room(disk=0, budget=0, keep=path)
        return path

    def _copies(self):
        files = []
        for entry in self.dir.glob(f"*-{LOW_KBPS}k-*{SUFFIX}"):
            try:
                stat = entry.stat()
            except FileNotFoundError:
                continue
            files.append((stat.st_mtime, stat.st_size, entry))
        return sorted(files)

    def _make_room(self, disk: int, budget: int, keep: Path | None) -> None:
        """Within the budget, and never below the free space the rest of the server needs."""
        files = self._copies()
        total = sum(size for _, size, _ in files)

        def short_of_disk():
            return shutil.disk_usage(self.dir).free - disk < self.min_free
        for _, size, entry in files:
            if total + budget <= self.max_bytes and not short_of_disk():
                break
            if entry == keep:
                continue
            entry.unlink(missing_ok=True)
            total -= size
        if short_of_disk():
            raise LowUnavailable("not enough free disk")

    def sweep(self) -> int:
        """Copies unused for longer than max_age, and pieces left by a build cut short (a restart). Returns how
        many files went."""
        if not self.dir.is_dir():
            return 0
        now, gone = self.clock(), 0
        old = [entry for _, _, entry in self._copies()]
        pieces = list(self.dir.glob(".in-*")) + list(self.dir.glob(".out-*"))
        for entry, limit in [(e, self.max_age) for e in old] + [(e, 600) for e in pieces]:
            try:
                if now - entry.stat().st_mtime > limit:
                    entry.unlink()
                    gone += 1
            except FileNotFoundError:
                pass
        # Older copies of this variant (another encoding or the 96 kbit/s AAC of before): never served again.
        for entry in self.dir.parent.glob("armonia-baja/*") if self.dir.name != "armonia-baja" else []:
            entry.unlink(missing_ok=True)
            gone += 1
        return gone

    async def worker(self, every: int = 3600):
        """Removes what passed its time even when nobody asks for a copy."""
        while True:
            try:
                await asyncio.to_thread(self.sweep)
            except OSError:
                pass
            await asyncio.sleep(every)

