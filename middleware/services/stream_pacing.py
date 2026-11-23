"""Hands a song to the network at a pace the path can carry instead of all at once.

Measured on the phone (18-11-2026, Tailscale capture on the server): Armonia passed a whole
3.5-4 MB song to Tailscale serve in a few milliseconds, which pushed it out in half a second,
about ten times what the phone's path carries. Up to one packet in eight was lost and resent,
and the song only started after the losses were recovered: 2.5-11 s instead of 0.2 s. Anything
asked for meanwhile (the next song, the app's own requests) waited behind those megabytes.

So, in three steps:
  1. the first piece at once;
  2. what the player needs before it can make a sound -- in an MP4/M4A the header and index,
     which in this library usually carry a 400-1000 KB embedded cover, plus a few seconds of
     audio -- quickly, but in spaced pieces so no queue on the way overflows;
  3. the rest at a steady rate that is still many times faster than playback.
Offline downloads opt out (they want the whole file and nothing is waiting for them).

On mobile data (the app says so) no more than AHEAD_SECONDS of the song goes ahead of what has played. Measured
19-11-2026 in the lab: with only the player limiting itself to 30 s, the phone's network still received a
whole 200 s song (1.34 MB) in 50 s, because what the server sends waits in the phone's TCP buffers, and a song
skipped then had cost all of it.
"""
import asyncio
import os
import struct
import time

# Minimum and maximum of step 2, and the audio sent after the header.
START_BYTES = int(os.getenv("ARMONIA_STREAM_BURST_KB", "128")) * 1024
START_MAX_BYTES = int(os.getenv("ARMONIA_STREAM_START_MAX_KB", "1536")) * 1024
AUDIO_AFTER_HEADER = 96 * 1024
# Step 2 rate, kilobits per second (about 2 MB/s).
FAST_KBPS = int(os.getenv("ARMONIA_STREAM_FAST_KBPS", "16000"))
# Step 3 rate when the app has not measured its path (older apps): 3x a 256 kbps song. 0 turns pacing off.
RATE_KBPS = int(os.getenv("ARMONIA_STREAM_RATE_KBPS", "768"))
# Ceiling of step 3 when the app reports a fast path (8x a 256 kbps song).
RATE_MAX_KBPS = int(os.getenv("ARMONIA_STREAM_RATE_MAX_KBPS", "2048"))
# Pieces small enough not to overflow a queue on the way (about 12 packets each).
PIECE_BYTES = 16 * 1024
# On mobile data, seconds of song sent ahead of playback at most (the listener's choice, 18-11-2026).
AHEAD_SECONDS = int(os.getenv("ARMONIA_STREAM_DATA_AHEAD_S", "30"))
# The app on mobile data (or another metered network).
DATA_HEADER = "x-armonia-datos"

DOWNLOAD_HEADER = "x-armonia-transfer"
# The app's measure of what reaches it on its current network, kbit/s (see rates()).
RATE_HEADER = "x-armonia-ritmo"
# Which file the app keeps for this song: "ligera" (the original without the cover embedded in its header,
# services/mp4_light.py), "ahorro" (Opus 64 kbit/s to save data and for bad connections,
# services/low_quality.py) or the original. "baja" (the 96 kbit/s AAC of before) is retired: always
# "not available now". The app stores each under its own key, so a variant must always be the same bytes:
# when one cannot be made this time the answer is an error, never another variant in its place.
LIGHT_HEADER = "x-armonia-variante"
VARIANTS = ("original", "ligera", "ahorro", "baja")


def wants_whole_file(headers) -> bool:
    """Offline downloads say so; everything else is someone waiting to listen."""
    return (headers.get(DOWNLOAD_HEADER) or "").strip().lower() == "download"


def variant(headers) -> str:
    value = (headers.get(LIGHT_HEADER) or "").strip().lower()
    return value if value in VARIANTS else "original"


def wants_light(headers) -> bool:
    return variant(headers) == "ligera"


def path_hint(headers) -> int | None:
    value = (headers.get(RATE_HEADER) or "").strip()
    if not value.isdigit():
        return None
    kbps = int(value)
    return kbps if 64 <= kbps <= 10_000_000 else None


# Below this the app's measure is a slow path (the app's PathRate.SLOW_KBPS).
SLOW_HINT_KBPS = 2000
# The app keeping the start of a song it may play next (NextSongPreload): never in a hurry.
PRELOAD_HEADER = "x-armonia-precarga"


def is_preload(headers) -> bool:
    return (headers.get(PRELOAD_HEADER) or "").strip() == "1"


def on_mobile_data(headers) -> bool:
    return (headers.get(DATA_HEADER) or "").strip() == "1"


def rates(hint_kbps: int | None, bitrate_kbps=None, preload: bool = False) -> tuple[int, int]:
    """(step 2, step 3) rates in kbit/s for one response.

    hint: what the app measured reaching it on its current network, or its first guess from the kind
    and quality of that network (see the app's PathRate). Measured 18-11-2026 over a relay from a
    university network: 25-220 KB/s; sending a song at 2048 kbit/s there built a queue of 1-2.5 s,
    then losses, then ~6 s without a single packet while TCP waited to resend. So step 3 stays at
    half of what the path carries, leaving room for covers, the next song and Tailscale's own
    messages, but never below 1.5x the song so playback keeps up; step 2 probes at twice the hint so
    a better path shows up in the next measure. Without a hint: the fixed defaults.

    On a slow path step 3 is just 1.5x the song. Measured 18-11-2026 19:52-19:54 (phone on mobile data with
    very low coverage, through the relay): at hint/2 (324-578 kbit/s for 128 kbit/s songs) the server sent
    510-936 kbit/s while the phone received 258-575; up to 765 KB waited in a queue, and a song chosen then
    got its first byte 9.3 s later, behind the previous one. Anything above what keeps playback ahead only
    waits in that queue. A preload goes all at that rate: it is never what someone is waiting for.
    """
    if RATE_KBPS <= 0:
        return FAST_KBPS, 0
    if hint_kbps is None:
        return FAST_KBPS, RATE_KBPS
    bitrate = bitrate_kbps if isinstance(bitrate_kbps, int) and bitrate_kbps > 0 else 256
    keep_up = max(int(bitrate * 1.5), 192)
    if hint_kbps < SLOW_HINT_KBPS:
        steady = keep_up
    else:
        steady = min(max(hint_kbps // 2, keep_up), max(RATE_MAX_KBPS, keep_up))
    fast = steady if preload else min(max(hint_kbps * 2, 1000), FAST_KBPS)
    return fast, steady


def mp4_header_end(head: bytes) -> int | None:
    """Where the audio data starts, judged from the top-level boxes at the start of the file.

    Returns the end of the 'moov' box (the index the player needs first) when it comes before
    the audio, None when that cannot be told from these bytes or the file is not an MP4.
    """
    pos = 0
    while pos + 8 <= len(head):
        size, kind = struct.unpack(">I4s", head[pos:pos + 8])
        if size == 1:
            if pos + 16 > len(head):
                return None
            size = struct.unpack(">Q", head[pos + 8:pos + 16])[0]
        if size < 8 or kind == b"mdat":
            return None
        if kind == b"moov":
            return pos + size
        if pos == 0 and kind != b"ftyp":
            return None
        pos += size
    return None


def start_size(header_end: int | None, offset: int, burst: int) -> int:
    """How much of this response goes in the fast step: what is left of header + some audio."""
    if header_end is None:
        return burst
    return min(max(burst, header_end + AUDIO_AFTER_HEADER - offset), START_MAX_BYTES)


async def paced(iterator, burst=None, rate_kbps=None, fast_kbps=None, from_start=True,
                header_end=None, offset=0, audio_bytes_per_s=None, ahead_s=None,
                clock=time.monotonic, sleep=asyncio.sleep):
    """from_start: the response begins at byte 0, so the header can be read from it. Otherwise
    header_end (from a separate look at the file's first bytes) and offset (where this response
    begins) say how much of the header the player still needs: a song half-saved on the phone
    resumes from the middle of its header.

    audio_bytes_per_s and ahead_s (mobile data): the audio after the header goes no further than ahead_s
    seconds of song past the time since the fast step ended, about where playback is. Playback starts after
    that and pauses only hold it back, so this never sends less than what is playing."""
    rate_kbps = RATE_KBPS if rate_kbps is None else rate_kbps
    fast_kbps = FAST_KBPS if fast_kbps is None else fast_kbps
    burst = START_BYTES if burst is None else burst
    start_bytes = start_size(header_end, offset, burst)
    try:
        if rate_kbps <= 0:
            async for block in iterator:
                yield block
            return
        rate = rate_kbps * 1000 / 8      # bytes per second, step 3
        fast = max(fast_kbps, rate_kbps) * 1000 / 8  # step 2
        head = b""
        decided = not from_start
        header_left = max(header_end - offset, 0) if header_end is not None and not from_start else 0
        limit_ahead = bool(audio_bytes_per_s) and ahead_s is not None
        started = None
        sent = 0
        async for block in iterator:
            if not decided:
                head += block[:64]
                end = mp4_header_end(head)
                if end is not None:
                    start_bytes = start_size(end, 0, burst)
                    header_left = end
                    decided = True
                elif len(head) >= 64:
                    decided = True
            for offset in range(0, len(block), PIECE_BYTES):
                piece = block[offset:offset + PIECE_BYTES]
                if started is None:
                    started = clock()
                if sent:
                    if sent < start_bytes:
                        due = started + sent / fast
                    else:
                        due = started + start_bytes / fast + (sent - start_bytes) / rate
                    if limit_ahead:
                        audio = max(sent - header_left, 0) / audio_bytes_per_s
                        due = max(due, started + start_bytes / fast + audio - ahead_s)
                    wait = due - clock()
                    if wait > 0:
                        await sleep(wait)
                sent += len(piece)
                yield piece
    finally:
        await iterator.aclose()
