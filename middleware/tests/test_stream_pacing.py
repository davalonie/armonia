import asyncio
import struct

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import get_current_session
from routes import stream
from services import session_stream, stream_pacing
from services.stream_pacing import PIECE_BYTES, mp4_header_end, paced, wants_whole_file


class FakeTime:
    def __init__(self):
        self.now = 100.0
        self.slept = []

    def clock(self):
        return self.now

    async def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


async def source(blocks, closed=None):
    try:
        for block in blocks:
            yield block
    finally:
        if closed is not None:
            closed.append(True)


def collect(gen):
    async def run():
        return [piece async for piece in gen]
    return asyncio.run(run())


def timed_pieces(blocks, t, **kw):
    gen = paced(source(blocks), clock=t.clock, sleep=t.sleep, **kw)

    async def run():
        return [(t.now, piece) async for piece in gen]
    return asyncio.run(run())


def mp4(header_kb, total_kb):
    """An MP4-shaped body: ftyp, a moov of header_kb (like one carrying a large cover), then mdat."""
    ftyp = struct.pack(">I4s", 24, b"ftyp") + b"M4A " + b"\0" * 12
    moov = struct.pack(">I4s", header_kb * 1024, b"moov") + b"\1" * (header_kb * 1024 - 8)
    rest = total_kb * 1024 - len(ftyp) - len(moov)
    mdat = struct.pack(">I4s", rest, b"mdat") + b"\2" * (rest - 8)
    return ftyp + moov + mdat


def test_three_steps_first_piece_then_fast_start_then_steady_rate():
    t = FakeTime()
    # Not an MP4: the start is the plain 128 KB. Fast 8000 kbit/s = 1 MB/s, steady 1024 kbit/s.
    timed = timed_pieces([b"x" * 1_048_576], t, burst=131_072, fast_kbps=8000, rate_kbps=1024)
    assert b"".join(p for _, p in timed) == b"x" * 1_048_576
    assert all(len(p) <= PIECE_BYTES for _, p in timed)
    start_pieces = 131_072 // PIECE_BYTES
    assert timed[0][0] == 100.0
    fast_gaps = [b[0] - a[0] for a, b in zip(timed[:start_pieces], timed[1:start_pieces], strict=False)]
    assert all(abs(g - PIECE_BYTES / 1_000_000) < 1e-9 for g in fast_gaps)
    steady_gaps = [b[0] - a[0] for a, b in zip(timed[start_pieces:], timed[start_pieces + 1:], strict=False)]
    assert all(abs(g - PIECE_BYTES / 128_000) < 1e-9 for g in steady_gaps)
    expected = 131_072 / 1_000_000 + (1_048_576 - 131_072 - PIECE_BYTES) / 128_000
    assert abs((t.now - 100.0) - expected) < 1e-6


def test_the_mp4_header_and_some_audio_go_in_the_fast_step():
    t = FakeTime()
    body = mp4(header_kb=500, total_kb=3000)
    timed = timed_pieces([body[i:i + 65_536] for i in range(0, len(body), 65_536)], t,
                         burst=131_072, fast_kbps=8000, rate_kbps=1024)
    assert b"".join(p for _, p in timed) == body
    header_end = 24 + 500 * 1024
    start = header_end + 96 * 1024
    # Everything up to the header plus 96 KB of audio arrives within start / 1 MB/s.
    sent = 0
    for when, piece in timed:
        sent += len(piece)
        if sent >= start:
            assert when - 100.0 <= start / 1_000_000 + 1e-9
            break
    assert t.now - 100.0 > 2.0  # and the rest at the steady rate


def test_a_huge_header_is_capped():
    assert mp4_header_end(mp4(header_kb=4000, total_kb=5000)[:64]) == 24 + 4000 * 1024
    t = FakeTime()
    body = mp4(header_kb=4000, total_kb=5000)
    timed = timed_pieces([body], t, burst=131_072, fast_kbps=8000, rate_kbps=1024)
    sent = 0
    for when, piece in timed:
        sent += len(piece)
        if sent == stream_pacing.START_MAX_BYTES + PIECE_BYTES:
            # The piece after the cap already waits at the steady rate.
            assert abs(when - 100.0 - stream_pacing.START_MAX_BYTES / 1_000_000) < 1e-6
            break


def test_a_range_from_the_middle_is_not_read_as_a_header():
    t = FakeTime()
    body = mp4(header_kb=500, total_kb=1000)
    timed_pieces([body], t, burst=131_072, fast_kbps=8000, rate_kbps=1024, from_start=False)
    with_header = FakeTime()
    timed_pieces([body], with_header, burst=131_072, fast_kbps=8000, rate_kbps=1024)
    assert t.now > with_header.now


def test_header_detection():
    assert mp4_header_end(mp4(500, 1000)[:64]) == 24 + 500 * 1024
    mdat_first = struct.pack(">I4s", 24, b"ftyp") + b"\0" * 16 + struct.pack(">I4s", 9000, b"mdat")
    assert mp4_header_end(mdat_first) is None
    assert mp4_header_end(b"ID3\x04" + b"\0" * 60) is None
    assert mp4_header_end(b"") is None


def test_a_small_song_never_waits_for_the_steady_rate():
    t = FakeTime()
    pieces = collect(paced(source([b"a" * 50_000, b"b" * 30_000]), burst=131_072, fast_kbps=8000,
                           rate_kbps=1024, clock=t.clock, sleep=t.sleep))
    assert b"".join(pieces) == b"a" * 50_000 + b"b" * 30_000
    assert t.now - 100.0 < 80_000 / 1_000_000


def test_rate_zero_turns_pacing_off():
    t = FakeTime()
    blocks = [b"z" * 500_000, b"y" * 500_000]
    pieces = collect(paced(source(blocks), burst=0, rate_kbps=0, clock=t.clock, sleep=t.sleep))
    assert pieces == blocks and t.slept == []


def test_closing_early_closes_the_source():
    closed = []

    async def run():
        gen = paced(source([b"x" * 1_000_000], closed), burst=0, rate_kbps=8_000_000)
        await gen.__anext__()
        await gen.aclose()
    asyncio.run(run())
    assert closed == [True]


def test_only_an_explicit_download_asks_for_the_whole_file():
    assert wants_whole_file({"x-armonia-transfer": "download"})
    assert wants_whole_file({"x-armonia-transfer": " Download "})
    assert not wants_whole_file({})
    assert not wants_whole_file({"x-armonia-transfer": "play"})


def _app(monkeypatch, calls, song=None, ignore_range=False):
    song = song if song is not None else b"\x00" * 400_000
    seen_ranges = []

    def handler(request):
        if request.url.path.endswith("/rest/getSong"):
            return httpx.Response(200, json={"subsonic-response": {"status": "ok", "song": {"id": "t", "size": len(song), "duration": 100}}})
        wanted = request.headers.get("range")
        seen_ranges.append(wanted)
        first, last = 0, len(song) - 1
        if wanted and not ignore_range:
            a, b = wanted.removeprefix("bytes=").split("-")
            first, last = int(a), int(b) if b else len(song) - 1
        part = song[first:last + 1]

        async def body():
            for i in range(0, len(part), 65_536):
                yield part[i:i + 65_536]
        headers = {"content-type": "audio/mp4", "content-length": str(len(part))}
        if wanted and not ignore_range:
            headers["content-range"] = f"bytes {first}-{last}/{len(song)}"
        return httpx.Response(206 if wanted and not ignore_range else 200, content=body(), headers=headers)

    real = httpx.AsyncClient
    monkeypatch.setattr(stream.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(session_stream.db, "check_session", lambda s: None)

    def spy(iterator, **kw):
        calls.append(kw)
        return stream_pacing.paced(iterator, rate_kbps=0)
    monkeypatch.setattr(stream, "paced", spy)
    app = FastAPI()
    app.include_router(stream.router)
    app.dependency_overrides[get_current_session] = lambda: {"username": "ana", "salt": "s", "token": "t"}
    return app, song, seen_ranges


def test_playback_is_paced_and_offline_downloads_are_not(monkeypatch):
    calls = []
    app, song, _ = _app(monkeypatch, calls)
    with TestClient(app) as c:
        played = c.get("/api/stream/t")
        assert played.status_code == 200 and played.content == song
        assert len(calls) == 1 and calls[0]["from_start"] is True
        downloaded = c.get("/api/stream/t", headers={"X-Armonia-Transfer": "download"})
        assert downloaded.status_code == 200 and downloaded.content == song
        assert len(calls) == 1


def test_resuming_inside_the_header_looks_up_where_the_header_ends(monkeypatch):
    calls = []
    body = mp4(header_kb=1109, total_kb=6375)
    app, song, ranges = _app(monkeypatch, calls, song=body)
    with TestClient(app) as c:
        resumed = c.get("/api/stream/t", headers={"Range": "bytes=212536-"})
        assert resumed.status_code == 206 and resumed.content == body[212536:]
    assert "bytes=0-63" in ranges
    assert calls[0]["from_start"] is False and calls[0]["offset"] == 212536
    assert calls[0]["header_end"] == 24 + 1109 * 1024
    # What is left of the header plus 96 KB of audio goes in the fast step.
    assert stream_pacing.start_size(calls[0]["header_end"], 212536, 131_072) == 24 + 1109 * 1024 + 96 * 1024 - 212536


def test_a_seek_far_into_the_song_does_not_look_at_the_header(monkeypatch):
    calls = []
    body = mp4(header_kb=500, total_kb=4000)
    app, song, ranges = _app(monkeypatch, calls, song=body)
    with TestClient(app) as c:
        assert c.get("/api/stream/t", headers={"Range": "bytes=3000000-"}).status_code == 206
    assert "bytes=0-63" not in ranges and calls[0]["header_end"] is None


def test_the_header_look_reads_only_a_few_bytes_even_if_the_range_is_ignored(monkeypatch):
    calls = []
    body = mp4(header_kb=500, total_kb=4000)
    _, _, _ = _app(monkeypatch, calls, song=body, ignore_range=True)
    client = stream.httpx.AsyncClient()
    end = asyncio.run(stream._header_end(client, {"id": "t"}))
    assert end == 24 + 500 * 1024


def test_on_mobile_data_no_more_than_thirty_seconds_ahead_of_playback():
    t = FakeTime()
    # 16 KB header (not counted as audio), then audio at 1 KB per second of song; fast step 128 KB.
    body = mp4(16, 1024)
    timed = timed_pieces([body], t, burst=131_072, fast_kbps=8000, rate_kbps=8000,
                         audio_bytes_per_s=1024, ahead_s=30)
    assert b"".join(p for _, p in timed) == body
    start_done = 100.0 + 131_072 / 1_000_000
    sent = 0
    for at, piece in timed:
        audio_before = max(sent - (24 + 16 * 1024), 0) / 1024  # ftyp + moov; seconds of song already sent when this piece left
        assert audio_before <= max(at - start_done, 0) + 30 + 1e-6
        sent += len(piece)
    # The whole ~1 MB song takes about its own length minus the 30 s ahead, not the 1 s of the steady rate.
    song_seconds = (len(body) - 16 * 1024) / 1024
    assert song_seconds - 30 - 20 < t.now - 100.0 < song_seconds


def test_without_mobile_data_the_steady_rate_alone():
    t = FakeTime()
    body = mp4(16, 1024)
    timed_pieces([body], t, burst=131_072, fast_kbps=8000, rate_kbps=8000)
    assert t.now - 100.0 < 2


def test_the_app_on_mobile_data_says_so(monkeypatch):
    calls = []
    app, song, _ = _app(monkeypatch, calls)
    with TestClient(app) as c:
        c.get("/api/stream/t")
        c.get("/api/stream/t", headers={"X-Armonia-Datos": "1"})
    assert calls[0]["ahead_s"] is None
    assert calls[1]["ahead_s"] == stream_pacing.AHEAD_SECONDS and calls[1]["audio_bytes_per_s"] > 0
