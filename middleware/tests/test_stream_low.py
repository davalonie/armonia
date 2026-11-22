"""The data-saving copy (Opus 64), and the rule that a variant is always the same bytes."""
import asyncio
import os
import shutil
import subprocess

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_stream_light import REAL_CLIENT, song

from auth import get_current_session
from routes import stream
from services import low_quality, session_stream, stream_pacing
from services.low_quality import LowStore, LowUnavailable
from services.mp4_light import LightCache


def run(coro):
    return asyncio.run(coro)


def fake_convert(output: bytes, calls: list):
    async def convert(src, dst, background=False):
        calls.append(src.read_bytes())
        await asyncio.sleep(0.01)
        dst.write_bytes(output)
    return convert


def fetcher(data: bytes):
    async def fetch(dest):
        dest.write_bytes(data)
    return fetch


# --- the store on disk ------------------------------------------------------------------------------
def test_a_copy_is_made_once_even_when_asked_for_twice_at_once(tmp_path):
    calls = []
    store = LowStore(tmp_path, convert=fake_convert(b"low" * 100, calls))

    async def both():
        return await asyncio.gather(store.get("t", 9, fetcher(b"original!")), store.get("t", 9, fetcher(b"original!")))
    first, second = run(both())
    assert first == second and first.read_bytes() == b"low" * 100
    assert calls == [b"original!"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [first.name]  # no pieces left behind
    assert run(store.get("t", 9, fetcher(b"x"))) == first and len(calls) == 1


def test_the_copy_goes_on_when_the_request_that_asked_for_it_leaves(tmp_path):
    calls = []
    store = LowStore(tmp_path, convert=fake_convert(b"low", calls))

    async def impatient():
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(store.get("t", 3, fetcher(b"abc")), timeout=0.001)
        await asyncio.sleep(0.05)
    run(impatient())
    assert store.path_for("t", 3).read_bytes() == b"low"


def test_failures_leave_nothing_and_the_next_request_tries_again(tmp_path):
    async def broken(src, dst, background=False):
        dst.write_bytes(b"half")
        raise LowUnavailable("ffmpeg could not convert the song")
    store = LowStore(tmp_path, convert=broken)
    with pytest.raises(LowUnavailable):
        run(store.get("t", 3, fetcher(b"abc")))
    assert list(tmp_path.iterdir()) == []
    store.convert = fake_convert(b"low", [])
    assert run(store.get("t", 3, fetcher(b"abc"))).read_bytes() == b"low"


def test_least_recently_used_copies_go_first_and_free_disk_is_kept(tmp_path, monkeypatch):
    store = LowStore(tmp_path, max_bytes=250, convert=fake_convert(b"x" * 100, []))
    a = run(store.get("a", 10, fetcher(b"a")))
    b = run(store.get("b", 10, fetcher(b"b")))
    os.utime(a, (1, 1))
    os.utime(b, (2, 2))
    run(store.get("a", 10, fetcher(b"a")))  # played again: now the most recent
    c = run(store.get("c", 10, fetcher(b"c")))
    assert a.exists() and c.exists() and not b.exists()

    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(low_quality.shutil, "disk_usage", lambda _: usage._replace(free=store.min_free - 1))
    with pytest.raises(LowUnavailable, match="disk"):
        run(store.get("d", 10, fetcher(b"d")))
    assert not any(tmp_path.glob("*.m4a"))  # it gave back what it could before refusing


def test_copies_unused_for_four_days_go_even_if_nobody_asks(tmp_path):
    now = [10 * 86400.0]
    store = LowStore(tmp_path, convert=fake_convert(b"x", []), clock=lambda: now[0])
    assert store.max_age == 4 * 86400 and store.max_bytes == 500 * 1024 * 1024
    old = run(store.get("old", 10, fetcher(b"o")))
    used = run(store.get("used", 10, fetcher(b"u")))
    os.utime(old, (now[0] - 4 * 86400 - 60,) * 2)
    os.utime(used, (now[0] - 4 * 86400 - 60,) * 2)
    os.utime(used, (now[0] - 3600,) * 2)  # played again an hour ago (ready() touches it): its four days start over
    assert store.sweep() == 1
    assert not old.exists() and used.exists()


def test_the_copies_of_before_are_removed(tmp_path):
    before = tmp_path / "armonia-baja"
    before.mkdir()
    (before / "abc-96k-v1.m4a").write_bytes(b"x")
    store = LowStore(tmp_path / "armonia-ahorro", convert=fake_convert(b"x", []))
    run(store.get("t", 3, fetcher(b"abc")))
    assert list(before.iterdir()) == []


def test_pieces_from_an_interrupted_build_are_swept(tmp_path):
    old = tmp_path / ".in-old"
    old.write_bytes(b"x")
    os.utime(old, (1, 1))
    recent = tmp_path / ".out-recent.m4a"
    recent.write_bytes(b"x")  # maybe another build right now: kept
    run(LowStore(tmp_path, convert=fake_convert(b"low", [])).get("t", 3, fetcher(b"abc")))
    assert not old.exists() and recent.exists()


def test_preparing_the_next_songs_never_delays_the_one_chosen_now(tmp_path):
    order = []

    def convert_named(delay):
        async def convert(src, dst, background=False):
            order.append(("start", src.read_bytes()))
            await asyncio.sleep(delay)
            dst.write_bytes(b"ok")
            order.append(("end", src.read_bytes()))
        return convert

    async def scenario():
        store = LowStore(tmp_path, convert=convert_named(0.1), slots=2, ahead_slots=1)
        store.prepare("n1", 3, fetcher(b"n1"))
        store.prepare("n2", 3, fetcher(b"n2"))
        await asyncio.sleep(0.01)
        t0 = asyncio.get_running_loop().time()
        await store.get("now", 3, fetcher(b"now"))
        waited = asyncio.get_running_loop().time() - t0
        assert waited < 0.18  # its own slot: not behind both preparations (0.2 s)
        await asyncio.sleep(0.25)
        assert store.ready("n1", 3) and store.ready("n2", 3)
    run(scenario())
    starts = [name for kind, name in order if kind == "start"]
    assert starts.index(b"now") < starts.index(b"n2")  # the second preparation waits its turn


def test_which_songs_get_a_copy():
    base = {"bitRate": 128, "size": 1000, "duration": 200}
    assert low_quality.applicable(base)  # every song, whatever its bitrate
    assert not low_quality.applicable({**base, "duration": 0})
    assert not low_quality.applicable({**base, "size": None})


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_real_ffmpeg_makes_the_same_small_opus_copy_every_time_without_the_cover(tmp_path):
    src = tmp_path / "f.m4a"
    cover = tmp_path / "c.jpg"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "nullsrc=s=600x600,geq=random(1)*255:128:128",
                    "-frames:v", "1", "-q:v", "2", str(cover)], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=20:c=pink:a=0.3", "-i", str(cover),
                    "-map", "0:a", "-map", "1:v", "-c:a", "aac", "-b:a", "128k", "-c:v", "copy",
                    "-disposition:v", "attached_pic", "-movflags", "+faststart", "-metadata", "title=Ficticia", str(src)],
                   check=True)
    one, two = tmp_path / "1.m4a", tmp_path / "2.m4a"
    run(low_quality.transcode(src, one))
    run(low_quality.transcode(src, two))
    data = one.read_bytes()
    assert data == two.read_bytes()
    end = stream_pacing.mp4_header_end(data[:64])  # index first: duration and seeking from the first request
    assert end is not None and end < 30_000 and b"Opus" in data[:end]
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name:format=bit_rate",
                            "-of", "csv=p=0", str(one)], capture_output=True, text=True, check=True).stdout.split()
    assert probe[0] == "opus,audio" and 50_000 < int(probe[1].strip(",")) < 90_000, probe
    assert len(data) < src.stat().st_size / 2
    assert b"Ficticia" not in data


# --- the route, against a fictitious Navidrome ----------------------------------------------------
LOW_BYTES, _, _ = song(cover=False, chunks=5, chunk=3000)


def _app(monkeypatch, tmp_path, data, bitrate=256, convert=None, light_fails=False):
    seen = []

    def handler(request):
        if request.url.path.endswith("/rest/getSong"):
            return httpx.Response(200, json={"subsonic-response": {"status": "ok", "song": {
                "id": "t", "suffix": "m4a", "size": len(data), "bitRate": bitrate, "duration": 200,
                "contentType": "audio/mp4"}}})
        wanted = request.headers.get("range")
        seen.append(wanted)
        if light_fails and wanted == "bytes=0-63":
            return httpx.Response(500)
        first, last = 0, len(data) - 1
        if wanted:
            a, b = wanted.removeprefix("bytes=").split("-")
            first, last = int(a), min(int(b), len(data) - 1) if b else len(data) - 1
        part = data[first:last + 1]
        headers = {"content-type": "audio/mp4", "content-length": str(len(part)), "accept-ranges": "bytes"}
        if wanted:
            headers["content-range"] = f"bytes {first}-{last}/{len(data)}"

        async def body():  # streamed, as Navidrome does (a bytes body would count as already read)
            for i in range(0, len(part), 65_536):
                yield part[i:i + 65_536]
        return httpx.Response(206 if wanted else 200, content=body(), headers=headers)

    monkeypatch.setattr(stream.httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(session_stream.db, "check_session", lambda s: None)
    monkeypatch.setattr(stream, "_light", LightCache())
    converted = []
    monkeypatch.setattr(stream, "_low", LowStore(tmp_path, convert=convert or fake_convert(LOW_BYTES, converted)))
    calls = []

    def spy(iterator, **kw):
        calls.append(kw)
        return stream_pacing.paced(iterator, rate_kbps=0)
    monkeypatch.setattr(stream, "paced", spy)
    app = FastAPI()
    app.include_router(stream.router)
    app.dependency_overrides[get_current_session] = lambda: {"username": "ana", "salt": "s", "token": "t"}
    return TestClient(app), seen, calls, converted


LOW = {"X-Armonia-Variante": "ahorro"}


def test_the_saving_copy_is_sent_complete_whole_and_by_ranges(monkeypatch, tmp_path):
    data, _, _ = song()
    c, seen, calls, converted = _app(monkeypatch, tmp_path, data, bitrate=128)
    with c:
        first = c.get("/api/stream/t", headers={**LOW, "X-Armonia-Ritmo": "400"})
        assert first.status_code == 200 and first.content == LOW_BYTES
        assert first.headers["x-armonia-variante"] == "ahorro" and first.headers["content-type"] == "audio/mp4"
        # Complete, with its length, even the first time: the player knows the duration and can seek.
        assert first.headers["content-length"] == str(len(LOW_BYTES))
        # Paced for a 64 kbit/s song on a slow path: 1.5x it (at least 192), probing at twice the measure.
        assert first.headers["x-armonia-ritmo"] == "rapido=1000; sostenido=192"
        whole = c.get("/api/stream/t", headers=LOW)
        assert whole.content == LOW_BYTES and whole.headers["content-length"] == str(len(LOW_BYTES))
        for rng, a, b in (("bytes=10-99", 10, 99), ("bytes=5000-", 5000, len(LOW_BYTES) - 1),
                          ("bytes=-100", len(LOW_BYTES) - 100, len(LOW_BYTES) - 1)):
            part = c.get("/api/stream/t", headers={**LOW, "Range": rng})
            assert part.status_code == 206 and part.content == LOW_BYTES[a:b + 1], rng
            assert part.headers["content-range"] == f"bytes {a}-{b}/{len(LOW_BYTES)}"
        assert c.get("/api/stream/t", headers={**LOW, "Range": f"bytes={len(LOW_BYTES)}-"}).status_code == 416
    assert converted == [data]  # made once, from the whole original
    assert seen.count(None) == 1


def test_a_range_in_the_middle_waits_for_the_complete_copy(monkeypatch, tmp_path):
    data, _, _ = song()
    c, _, _, converted = _app(monkeypatch, tmp_path, data)
    with c:
        part = c.get("/api/stream/t", headers={**LOW, "Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == LOW_BYTES[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{len(LOW_BYTES)}"


def test_the_retired_low_copy_is_never_other_bytes(monkeypatch, tmp_path):
    data, _, _ = song()
    c, _, _, converted = _app(monkeypatch, tmp_path, data, bitrate=256)
    with c:
        # An app from before asks for "baja": not available now, so it plays its light copy instead.
        assert c.get("/api/stream/t", headers={"X-Armonia-Variante": "baja"}).status_code == 503
    assert converted == []


def test_a_variant_that_cannot_be_made_now_is_an_error_never_another_variant(monkeypatch, tmp_path):
    data, _, _ = song()

    async def broken(src, dst, background=False):
        raise LowUnavailable("ffmpeg could not convert the song")
    c, _, _, _ = _app(monkeypatch, tmp_path, data, convert=broken)
    with c:
        assert c.get("/api/stream/t", headers=LOW).status_code == 503
    # Same for the light copy: a moment when its header cannot be read is not a reason to send the original
    # under the light copy's name (the phone would mix both files in one song).
    c, _, _, _ = _app(monkeypatch, tmp_path, data, light_fails=True)
    with c:
        assert c.get("/api/stream/t", headers={"X-Armonia-Variante": "ligera"}).status_code == 503
        assert c.get("/api/stream/t", headers={"X-Armonia-Variante": "original"}).content == data


def test_downloads_and_unknown_variants_get_the_original(monkeypatch, tmp_path):
    data, _, _ = song()
    c, _, _, converted = _app(monkeypatch, tmp_path, data)
    with c:
        download = c.get("/api/stream/t", headers={**LOW, "X-Armonia-Transfer": "download"})
        assert download.content == data and download.headers["x-armonia-variante"] == "original"
        assert c.get("/api/stream/t", headers={"X-Armonia-Variante": "otra"}).content == data
    assert converted == []


def test_the_app_can_ask_for_the_next_songs_to_be_ready(monkeypatch, tmp_path):
    data, _, _ = song()
    c, _, _, converted = _app(monkeypatch, tmp_path, data)
    with c:
        answer = c.post("/api/stream/preparar", json={"ids": ["t", "t"]})
        assert answer.status_code == 202 and answer.headers["x-armonia-preparadas"] == "1"
        assert c.post("/api/stream/preparar", json={"ids": ["a", "b", "c", "d"]}).status_code == 422  # at most 3
        for _ in range(100):
            if stream._low.ready("t", len(data)):
                break
            import time
            time.sleep(0.01)
        assert stream._low.ready("t", len(data)) is not None
    assert converted == [data]


def test_only_copies_made_ahead_go_at_lower_priority(tmp_path):
    seen = []

    async def convert(src, dst, background=False):
        seen.append((src.read_bytes(), background))
        dst.write_bytes(b"ok")

    async def scenario():
        store = LowStore(tmp_path, convert=convert)
        await store.get("now", 3, fetcher(b"now"))
        store.prepare("next", 3, fetcher(b"next"))
        await asyncio.sleep(0.05)
    run(scenario())
    assert sorted(seen) == [(b"next", True), (b"now", False)]
