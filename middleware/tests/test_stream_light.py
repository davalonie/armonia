"""The light copy of a song (no embedded cover) and adaptive pacing, with fictitious MP4 files."""
import struct

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import get_current_session
from routes import stream
from services import mp4_light, session_stream, stream_pacing
from services.mp4_light import LightCache, NotLightened, lighten
from services.stream_pacing import mp4_header_end

REAL_CLIENT = httpx.AsyncClient


def box(kind, body):
    return struct.pack(">I4s", 8 + len(body), kind) + body


def song(cover_kb=300, chunks=6, chunk=4096, co64=False, quicktime_meta=False, cover=True, offsets_base=None):
    """ftyp + moov (track with chunk offsets, udta/meta/ilst with title and cover) + free + mdat."""
    audio = bytes((i * 7 + 3) % 251 for i in range(chunks * chunk))
    ftyp = box(b"ftyp", b"M4A \x00\x00\x00\x00M4A mp42isom")
    free = box(b"free", b"\x00" * 8)

    def moov(offsets):
        width = ">Q" if co64 else ">I"
        table = box(b"co64" if co64 else b"stco",
                    b"\x00\x00\x00\x00" + struct.pack(">I", len(offsets)) + b"".join(struct.pack(width, o) for o in offsets))
        stbl = box(b"stbl", box(b"stsd", b"\x00" * 16) + table)
        trak = box(b"trak", box(b"tkhd", b"\x00" * 84) + box(b"mdia", box(b"mdhd", b"\x00" * 24) + box(b"minf", stbl)))
        items = box(b"\xa9nam", box(b"data", b"\x00\x00\x00\x01\x00\x00\x00\x00Pista ficticia"))
        if cover:
            items += box(b"covr", box(b"data", b"\x00\x00\x00\x0d\x00\x00\x00\x00" + bytes(cover_kb * 1024)))
        meta_body = box(b"hdlr", b"\x00" * 25) + box(b"ilst", items)
        meta = box(b"meta", meta_body if quicktime_meta else b"\x00\x00\x00\x00" + meta_body)
        return box(b"moov", box(b"mvhd", b"\x00" * 100) + trak + box(b"udta", meta))

    first = len(ftyp) + len(moov([0] * chunks)) + len(free) + 8
    offsets = [(first if offsets_base is None else offsets_base) + i * chunk for i in range(chunks)]
    data = ftyp + moov(offsets) + free + box(b"mdat", audio)
    return data, offsets, chunk


def light_file(data):
    end = mp4_header_end(data[:64])
    light = lighten(data[:end])
    return light.header + data[end:], light


def offsets_of(data):
    pos = data.find(b"stco")
    width = 4
    if pos < 0:
        pos, width = data.find(b"co64"), 8
    count = struct.unpack(">I", data[pos + 8:pos + 12])[0]
    fmt = f">{count}{'I' if width == 4 else 'Q'}"
    return list(struct.unpack(fmt, data[pos + 12:pos + 12 + count * width]))


@pytest.mark.parametrize("co64,quicktime_meta", [(False, False), (True, False), (False, True)])
def test_light_copy_drops_the_cover_and_keeps_every_chunk_pointing_at_the_same_audio(co64, quicktime_meta):
    data, offsets, chunk = song(co64=co64, quicktime_meta=quicktime_meta)
    light, info = light_file(data)
    assert b"covr" not in light and b"covr" in data
    assert len(data) - len(light) == info.cut >= 300 * 1024
    assert b"Pista ficticia" in light
    new_offsets = offsets_of(light)
    assert new_offsets == [o - info.cut for o in offsets]
    for old, new in zip(offsets, new_offsets, strict=True):
        assert light[new:new + chunk] == data[old:old + chunk]
    # Every box size still adds up: walking the light header lands exactly on the original 'free'.
    assert mp4_header_end(light[:64]) == len(info.header)
    assert light[len(info.header) + 4:len(info.header) + 8] == b"free"


def test_without_a_cover_or_with_odd_files_the_original_is_kept():
    data, _, _ = song(cover=False)
    with pytest.raises(NotLightened):
        light_file(data)
    data, _, _ = song(offsets_base=100)  # chunk offsets pointing inside the header
    with pytest.raises(NotLightened):
        light_file(data)
    ftyp = box(b"ftyp", b"M4A \x00\x00\x00\x00")
    with pytest.raises(NotLightened):
        lighten(ftyp + box(b"mdat", b"x" * 100) + box(b"moov", b""))
    with pytest.raises(NotLightened):
        lighten(ftyp + box(b"moov", box(b"mvex", b"")))


def test_light_cache_keeps_recent_headers_within_its_budget():
    cache = LightCache(max_bytes=250)
    a, b = mp4_light.Light(b"a" * 100, 500), mp4_light.Light(b"b" * 100, 500)
    cache.put("a", a)
    cache.put("b", b)
    assert cache.get("a") == (True, a)
    cache.put("c", mp4_light.Light(b"c" * 100, 500))
    assert cache.get("b") == (False, None) and cache.get("a")[0] and cache.get("c")[0]
    cache.put("x", None)
    assert cache.get("x") == (True, None)


def test_rates_follow_the_path_the_app_measured():
    assert stream_pacing.rates(None, 256) == (stream_pacing.FAST_KBPS, stream_pacing.RATE_KBPS)
    # Fast path (Wi-Fi at home): probe at the ceiling, steady at the ceiling.
    assert stream_pacing.rates(50_000, 256) == (16000, 2048)
    # Relay from eduroam, ~1 Mbit/s: steady just ahead of the song (1.5x), probe at twice.
    assert stream_pacing.rates(1000, 256) == (2000, 384)
    assert stream_pacing.rates(1000, 128) == (2000, 192)
    # A good path: steady at half of it.
    assert stream_pacing.rates(6000, 128) == (12000, 2048) and stream_pacing.rates(3000, 128) == (6000, 1500)
    # A preload never hurries, on any path.
    assert stream_pacing.rates(1000, 128, preload=True) == (192, 192)
    assert stream_pacing.rates(50_000, 256, preload=True) == (2048, 2048)
    # Slower than the song: never below 1.5x the song.
    assert stream_pacing.rates(300, 256) == (1000, 384)
    assert stream_pacing.rates(300, None) == (1000, 384)


def test_headers_are_read_strictly():
    assert stream_pacing.path_hint({"x-armonia-ritmo": "1200"}) == 1200
    for bad in ("", "abc", "-5", "12.5", "10", "99999999999"):
        assert stream_pacing.path_hint({"x-armonia-ritmo": bad}) is None
    assert stream_pacing.wants_light({"x-armonia-variante": " Ligera "})
    assert not stream_pacing.wants_light({"x-armonia-variante": "original"})


# --- the route, against a fictitious Navidrome that serves byte ranges ---------------------------
def _app(monkeypatch, data, suffix="m4a", honour_ranges=True):
    seen = []

    def handler(request):
        if request.url.path.endswith("/rest/getSong"):
            return httpx.Response(200, json={"subsonic-response": {"status": "ok", "song": {
                "id": "t", "suffix": suffix, "size": len(data), "bitRate": 256, "contentType": "audio/mp4"}}})
        wanted = request.headers.get("range")
        seen.append(wanted)
        first, last = 0, len(data) - 1
        if wanted and honour_ranges:
            a, b = wanted.removeprefix("bytes=").split("-")
            first, last = int(a), min(int(b), len(data) - 1) if b else len(data) - 1
        part = data[first:last + 1]

        async def body():
            for i in range(0, len(part), 65_536):
                yield part[i:i + 65_536]
        headers = {"content-type": "audio/mp4", "content-length": str(len(part)), "accept-ranges": "bytes"}
        if wanted and honour_ranges:
            headers["content-range"] = f"bytes {first}-{last}/{len(data)}"
        return httpx.Response(206 if wanted and honour_ranges else 200, content=body(), headers=headers)

    monkeypatch.setattr(stream.httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(session_stream.db, "check_session", lambda s: None)
    monkeypatch.setattr(stream, "_light", LightCache())
    calls = []

    def spy(iterator, **kw):
        calls.append(kw)
        return stream_pacing.paced(iterator, rate_kbps=0)
    monkeypatch.setattr(stream, "paced", spy)
    app = FastAPI()
    app.include_router(stream.router)
    app.dependency_overrides[get_current_session] = lambda: {"username": "ana", "salt": "s", "token": "t"}
    return TestClient(app), seen, calls


LIGHT = {"X-Armonia-Variante": "ligera"}


def test_the_app_gets_the_light_copy_whole_and_by_ranges(monkeypatch):
    data, _, _ = song()
    light, info = light_file(data)
    head = len(info.header)
    c, seen, calls = _app(monkeypatch, data)
    with c:
        whole = c.get("/api/stream/t", headers=LIGHT)
        assert whole.status_code == 200 and whole.content == light
        assert whole.headers["content-length"] == str(len(light))
        for rng, first, last in (("bytes=0-99", 0, 99), (f"bytes=100-{head + 5000}", 100, head + 5000),
                                 (f"bytes={head + 10}-", head + 10, len(light) - 1), ("bytes=-1000", len(light) - 1000, len(light) - 1),
                                 (f"bytes={len(light) - 10}-{len(light) + 500}", len(light) - 10, len(light) - 1)):
            part = c.get("/api/stream/t", headers={**LIGHT, "Range": rng})
            assert part.status_code == 206, rng
            assert part.content == light[first:last + 1], rng
            assert part.headers["content-range"] == f"bytes {first}-{last}/{len(light)}", rng
        assert c.get("/api/stream/t", headers={**LIGHT, "Range": f"bytes={len(light)}-"}).status_code == 416
    # The header was rebuilt once (two small reads of the original), then reused from memory.
    assert seen.count("bytes=0-63") == 1
    # The original bytes behind the cut were asked for at their real positions.
    assert f"bytes={head + 10 + info.cut}-{len(data) - 1}" in seen
    # A range inside the rebuilt header does not touch the original audio; pacing knows where it ends.
    assert not any(r and r.startswith(f"bytes={head + info.cut}-99") for r in seen if r)
    assert all(call["header_end"] == head for call in calls)


def test_older_apps_downloads_and_other_formats_get_the_original(monkeypatch):
    data, _, _ = song()
    c, _, _ = _app(monkeypatch, data)
    with c:
        assert c.get("/api/stream/t").content == data
        assert c.get("/api/stream/t", headers={**LIGHT, "X-Armonia-Transfer": "download"}).content == data
    c, _, _ = _app(monkeypatch, data, suffix="mp3")
    with c:
        assert c.get("/api/stream/t", headers=LIGHT).content == data


def test_a_source_that_ignores_ranges_falls_back_to_the_original(monkeypatch):
    data, _, _ = song()
    c, seen, _ = _app(monkeypatch, data, honour_ranges=False)
    with c:
        first = c.get("/api/stream/t", headers=LIGHT)
        assert first.status_code == 200 and first.content == data
        again = c.get("/api/stream/t", headers=LIGHT)
        assert again.content == data
    assert seen.count("bytes=0-63") == 1  # the verdict is remembered


def test_the_rates_come_from_the_apps_measure_and_are_told_back(monkeypatch):
    data, _, _ = song()
    c, _, calls = _app(monkeypatch, data)
    with c:
        measured = c.get("/api/stream/t", headers={**LIGHT, "X-Armonia-Ritmo": "1000"})
        assert measured.headers["x-armonia-ritmo"] == "rapido=2000; sostenido=384"
        unknown = c.get("/api/stream/t", headers=LIGHT)
        assert unknown.headers["x-armonia-ritmo"] == \
            f"rapido={stream_pacing.FAST_KBPS}; sostenido={stream_pacing.RATE_KBPS}"
    assert (calls[0]["fast_kbps"], calls[0]["rate_kbps"]) == (2000, 384)
    with c:
        preload = c.get("/api/stream/t", headers={**LIGHT, "X-Armonia-Ritmo": "1000", "X-Armonia-Precarga": "1"})
        assert preload.headers["x-armonia-ritmo"] == "rapido=384; sostenido=384"
