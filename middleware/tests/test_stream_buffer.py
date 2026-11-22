"""Whole-song memory buffer and provider redirects for external streams."""
import asyncio

import httpx
import pytest

from routes import tracks
from services import preview_stream, stream_buffer
from services.preview_stream import StreamInfoCache, UpstreamInfo


@pytest.fixture
def buffer(monkeypatch):
    monkeypatch.setattr(stream_buffer, "_songs", {})
    monkeypatch.setattr(stream_buffer, "RETRY_DELAYS", (0, 0))
    monkeypatch.delenv("MUSIC_STREAM_BUFFER_MAX_BYTES", raising=False)
    state = {"fetches": 0, "gate": None, "fail_after": None, "cuts": None, "starts": [], "status": None}

    async def relay(client, url, headers, start, end):
        state["fetches"] += 1
        state["starts"].append(start)
        if state["status"]:
            raise httpx.HTTPStatusError("refused", request=httpx.Request("GET", url),
                                        response=httpx.Response(state["status"]))
        for n in range(start, end + 1, 4):
            if state["gate"]:
                await state["gate"].wait()
            if state["fail_after"] is not None and n >= state["fail_after"]:
                if state["cuts"] is None or state["cuts"] > 0:
                    if state["cuts"]:
                        state["cuts"] -= 1
                    raise httpx.RemoteProtocolError("cut")
            yield bytes(range(n, min(n + 4, end + 1)))

    monkeypatch.setattr(stream_buffer, "relay_ranged", relay)
    return state


async def collect(song, start, end):
    return b"".join([block async for block in song.read(start, end)])


def test_first_bytes_seeks_and_replays_come_from_one_fetch(buffer):
    async def run():
        buffer["gate"] = asyncio.Event()
        song = stream_buffer.start("alice", "abcdefghijk", "https://x", {}, 40, "audio/mp4")
        # A seek far ahead while the song is still arriving waits for those bytes, then answers.
        ahead = asyncio.create_task(collect(song, 30, 39))
        await asyncio.sleep(.01)
        assert not ahead.done()
        buffer["gate"].set()
        assert await ahead == bytes(range(30, 40))
        assert await collect(song, 0, 39) == bytes(range(40)) and song.complete
        # Later requests for the same song by the same user: no provider contact at all.
        again = stream_buffer.get("alice", "abcdefghijk")
        assert again is song and await collect(again, 12, 20) == bytes(range(12, 21))
        assert stream_buffer.start("alice", "abcdefghijk", "https://x", {}, 40, "audio/mp4") is song
        assert buffer["fetches"] == 1
        # Another user never reads this copy.
        assert stream_buffer.get("bob", "abcdefghijk") is None
    asyncio.run(run())


def test_failed_fetch_is_never_served_as_a_complete_song_and_is_retried(buffer):
    async def run():
        buffer["fail_after"] = 8
        song = stream_buffer.start("alice", "abcdefghijk", "https://x", {}, 40, "audio/mp4")
        with pytest.raises(httpx.RemoteProtocolError):
            await collect(song, 0, 39)
        assert stream_buffer.get("alice", "abcdefghijk") is None  # Dropped: the next play asks the provider again.
        buffer["fail_after"] = None
        fresh = stream_buffer.start("alice", "abcdefghijk", "https://x", {}, 40, "audio/mp4")
        assert await collect(fresh, 0, 39) == bytes(range(40))
        assert buffer["fetches"] == stream_buffer.FILL_ATTEMPTS + 1  # Bounded: three tries, then given up.
    asyncio.run(run())


def test_a_dropped_provider_connection_resumes_from_the_missing_byte(buffer):
    """Regression: one cut chunk used to end a song that was already playing."""
    async def run():
        buffer["fail_after"], buffer["cuts"] = 8, 1
        song = stream_buffer.start("alice", "abcdefghijk", "https://x", {}, 40, "audio/mp4")
        assert await collect(song, 0, 39) == bytes(range(40)) and song.complete and not song.error
        assert buffer["starts"] == [0, 8] and song.retries == 1  # Continued, not restarted.
    asyncio.run(run())


@pytest.mark.parametrize("status,tries", [(403, 1), (404, 1), (503, 3), (429, 3)])
def test_refused_locations_are_not_retried_but_server_errors_are(buffer, status, tries):
    async def run():
        buffer["status"] = status
        song = stream_buffer.start("alice", "abcdefghijk", "https://x", {}, 40, "audio/mp4")
        with pytest.raises(httpx.RemoteProtocolError):
            await collect(song, 0, 39)
        assert buffer["fetches"] == tries
    asyncio.run(run())


def test_a_song_being_listened_to_is_never_evicted_under_the_player(buffer, monkeypatch):
    """Regression: preparing other songs could evict the playing one and cancel its download."""
    monkeypatch.setattr(stream_buffer, "PER_USER", 2)
    async def run():
        buffer["gate"] = asyncio.Event()
        playing = stream_buffer.start("alice", "playing0000", "https://x", {}, 40, "audio/mp4")
        listener = asyncio.create_task(collect(playing, 0, 39))
        await asyncio.sleep(.01)
        assert playing.readers == 1
        # Two more preparations for the same user, beyond the per-user limit of two.
        stream_buffer.start("alice", "nextsong000", "https://x", {}, 40, "audio/mp4")
        stream_buffer.start("alice", "firsthit000", "https://x", {}, 40, "audio/mp4")
        assert stream_buffer.get("alice", "playing0000") is playing and not playing.task.cancelled()
        buffer["gate"].set()
        assert await listener == bytes(range(40)) and not playing.error
        assert playing.readers == 0
        # Once nobody reads it, the per-user limit applies again (least recently used first).
        stream_buffer.start("alice", "another0000", "https://x", {}, 40, "audio/mp4")
        assert sorted(k[1] for k in stream_buffer._songs) == ["another0000", "playing0000"]
    asyncio.run(run())


def test_limits_keep_memory_bounded_and_can_switch_the_buffer_off(buffer, monkeypatch):
    async def run():
        monkeypatch.setenv("MUSIC_STREAM_BUFFER_MAX_BYTES", "100")
        assert stream_buffer.start("alice", "toolargesong", "https://x", {}, 101, "audio/mp4") is None
        first = stream_buffer.start("alice", "song0000001", "https://x", {}, 40, "audio/mp4")
        await collect(first, 0, 39)
        second = stream_buffer.start("alice", "song0000002", "https://x", {}, 40, "audio/mp4")
        await collect(second, 0, 39)
        stream_buffer.get("alice", "song0000001")  # Most recently used survives.
        third = stream_buffer.start("bob", "song0000003", "https://x", {}, 40, "audio/mp4")
        assert third is not None and stream_buffer.get("alice", "song0000002") is None
        assert stream_buffer.get("alice", "song0000001") is not None
        monkeypatch.setenv("MUSIC_STREAM_BUFFER_MAX_BYTES", "0")
        assert stream_buffer.start("alice", "song0000004", "https://x", {}, 40, "audio/mp4") is None
        monkeypatch.setenv("MUSIC_STREAM_BUFFER_MAX_BYTES", str(10**9))
        for n in range(stream_buffer.PER_USER + 3):
            await collect(stream_buffer.start("carol", f"carol{n:06d}", "https://x", {}, 8, "audio/mp4"), 0, 7)
        assert sum(1 for owner, _ in stream_buffer._songs if owner == "carol") == stream_buffer.PER_USER
        stream_buffer.forget("carol")
        assert not any(owner == "carol" for owner, _ in stream_buffer._songs)
    asyncio.run(run())


def redirect(location, status=302):
    request = httpx.Request("GET", "https://a.googlevideo.com/audio")
    response = httpx.Response(status, headers={"location": location} if location else {}, request=request)
    return httpx.HTTPStatusError("redirect", request=request, response=response)


def test_provider_redirect_between_its_media_hosts_is_followed(monkeypatch):
    monkeypatch.setattr(tracks, "_stream_info_cache", StreamInfoCache())
    seen = []

    async def probe(client, url, headers):
        seen.append((url, dict(headers)))
        if "a.googlevideo.com" in url:
            raise redirect("https://b.googlevideo.com/audio?expire=9999999999")
        return UpstreamInfo(total=10, content_type="audio/mp4")

    monkeypatch.setattr(tracks, "probe_upstream", probe)
    url, info = asyncio.run(tracks._probe(None, "https://a.googlevideo.com/audio", {"User-Agent": "x", "Cookie": "no"}, "abcdefghijk"))
    assert url.startswith("https://b.googlevideo.com/") and info.total == 10
    assert "Cookie" not in seen[1][1]  # Only the reduced headers travel to the new location.
    assert tracks._stream_info_cache.get("abcdefghijk")[0] == url  # The final location is what gets reused.


@pytest.mark.parametrize("location,video", [
    ("https://evil.example/audio", "abcdefghijk"),          # another domain
    ("http://b.googlevideo.com/audio", "abcdefghijk"),      # not https
    (None, "abcdefghijk"),                                   # no location
    ("https://b.googlevideo.com/audio", "authorized"),      # not a provider stream: never followed
])
def test_any_other_redirect_stays_an_error(monkeypatch, location, video):
    monkeypatch.setattr(tracks, "_stream_info_cache", StreamInfoCache())

    async def probe(client, url, headers):
        raise redirect(location)

    monkeypatch.setattr(tracks, "probe_upstream", probe)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(tracks._probe(None, "https://a.googlevideo.com/audio", {}, video))


def test_redirect_loop_is_bounded(monkeypatch):
    monkeypatch.setattr(tracks, "_stream_info_cache", StreamInfoCache())
    calls = []

    async def probe(client, url, headers):
        calls.append(url)
        raise redirect("https://a.googlevideo.com/audio")

    monkeypatch.setattr(tracks, "probe_upstream", probe)
    with pytest.raises(httpx.HTTPError):
        asyncio.run(tracks._probe(None, "https://a.googlevideo.com/audio", {}, "abcdefghijk"))
    assert len(calls) == 4 and preview_stream.CHUNK_SIZE
