"""The stream-location extractor is reused between songs and replaced when it fails or ages."""
import contextlib

import pytest

from services import ytdlp_service as y


class Fake:
    made = []

    def __init__(self):
        self.calls, self.closed = [], False
        Fake.made.append(self)

    def extract_info(self, url, download):
        assert not download and not self.closed
        self.calls.append(url)
        if url.endswith("failfailfai"):
            raise RuntimeError("provider down")
        return {"url": "https://x.googlevideo.com/" + url[-11:], "http_headers": {"User-Agent": "x"}}


@pytest.fixture
def resolver(monkeypatch):
    Fake.made = []

    @contextlib.contextmanager
    def ytdl(opts):
        assert opts["format"].startswith("bestaudio") and opts["noplaylist"]
        fake = Fake()
        try:
            yield fake
        finally:
            fake.closed = True  # The private cookie copy goes away with the instance.

    monkeypatch.setattr(y, "_ytdl", ytdl)
    fresh = y._StreamResolver()
    monkeypatch.setattr(y, "_stream_resolver", fresh)
    return fresh


def test_one_instance_resolves_consecutive_songs(resolver):
    assert y.get_stream_info("abcdefghijk") == ("https://x.googlevideo.com/abcdefghijk", {"User-Agent": "x"})
    assert y.get_stream_info("second_song")[0].endswith("second_song")
    assert len(Fake.made) == 1 and len(Fake.made[0].calls) == 2 and not Fake.made[0].closed


def test_a_failed_or_old_instance_is_closed_and_replaced(resolver, monkeypatch):
    y.get_stream_info("abcdefghijk")
    with pytest.raises(RuntimeError):
        y.get_stream_info("failfailfai")
    assert Fake.made[0].closed
    y.get_stream_info("second_song")
    assert len(Fake.made) == 2 and not Fake.made[1].closed
    clock = [y.time.monotonic() + y._StreamResolver.REUSE_SECONDS + 1]
    monkeypatch.setattr(y.time, "monotonic", lambda: clock[0])
    y.get_stream_info("third_song1")
    assert len(Fake.made) == 3 and Fake.made[1].closed
