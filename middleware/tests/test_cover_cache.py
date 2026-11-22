"""Covers may be kept on the phone (the app honours no-store, so before 0.5.3 it kept none on disk)."""
from starlette.requests import Request
from starlette.responses import Response

import main


def request(path, **query):
    qs = "&".join(f"{k}={v}" for k, v in query.items()).encode()
    return Request({"type": "http", "method": "GET", "path": path, "query_string": qs, "headers": []})


def test_a_versioned_cover_is_kept_for_good_and_others_for_a_day():
    image = Response(b"jpg", media_type="image/jpeg")
    assert main._cacheable_cover(request("/api/library/getCoverArt", id="al-2nKqlpd7Afj1Ky5d1bnjBn_6745f3b2", size=128), image)
    assert image.headers["cache-control"] == "private, max-age=31536000, immutable"
    other = Response(b"jpg", media_type="image/jpeg")
    assert main._cacheable_cover(request("/api/library/getCoverArt", id="2nKqlpd7Afj1Ky5d1bnjBn"), other)
    assert other.headers["cache-control"] == "private, max-age=604800"
    # Asked again with its ETag: 304 keeps the phone's copy, for another week.
    same = Response(status_code=304)
    assert main._cacheable_cover(request("/api/library/getCoverArt", id="mf-3gtxUVyHrTmWZZyopo0lOL"), same)
    assert same.headers["cache-control"] == "private, max-age=604800"


def test_nothing_else_is_kept():
    assert not main._cacheable_cover(request("/api/library/getSong", id="x"), Response(b"{}", media_type="application/json"))
    assert not main._cacheable_cover(request("/api/library/getCoverArt", id="al-x_1"), Response(b"{}", status_code=404, media_type="image/jpeg"))
    assert not main._cacheable_cover(request("/api/library/getCoverArt", id="al-x_1"), Response(b"{}", media_type="application/json"))


def test_a_release_cover_is_kept_a_week_and_its_errors_are_not():
    path = "/api/home/releases/0a0d1700-0000-4000-8000-000000000001/cover"
    image = Response(b"\xff\xd8", media_type="image/jpeg")
    assert main._cacheable_cover(request(path, account="ns"), image)
    assert image.headers["cache-control"] == "private, max-age=604800"
    assert not main._cacheable_cover(request(path), Response(b"{}", status_code=404, media_type="application/json"))
    assert not main._cacheable_cover(request("/api/home/releases/0a0d1700-0000-4000-8000-000000000001"),
                                     Response(b"{}", media_type="application/json"))
