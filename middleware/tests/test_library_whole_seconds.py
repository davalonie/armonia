"""The library reports durations in whole seconds, cut off; the lookup must not read them as exact."""
import asyncio
import importlib.util

import pytest

from services import navidrome_client as nd


def _lookup(monkeypatch, reported):
    # Other tests replace find_song_id; load the real implementation under another name.
    spec = importlib.util.spec_from_file_location("lookup_whole_seconds_test", nd.__file__)
    actual = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(actual)

    async def search(*args):
        return [{"id": "local", "title": "Song", "artist": "Fixture", "album": "Song", "duration": reported}]

    monkeypatch.setattr(actual, "search_songs", search)
    wanted = {"title": "Song", "artist": "Fixture", "album": "Song", "duration": 119.048}
    return asyncio.run(actual.find_song_id("Fixture", "Song", "fixture", "s", "t", wanted))


@pytest.mark.parametrize("reported,expected", [
    (116, "local"),   # a 116.5 s file: 2.5 s away, although 119.048 - 116 looks like 3.05
    (119, "local"),
    (122, "local"),   # the wanted length falls short of it by 2.95 s
    (115, None),      # at best 115.999 s: more than 3 s away
    (123, None),
    (116.0, "local"),
    (115.9, None),    # a fractional report is exact
    (None, None),
])
def test_whole_second_report_is_a_range_not_an_exact_length(monkeypatch, reported, expected):
    assert _lookup(monkeypatch, reported) == expected


def test_real_duration_keeps_values_it_cannot_refine():
    assert nd._real_duration(None, 100) is None
    assert nd._real_duration(116, None) == 116
    assert nd._real_duration(116.4, 119) == 116.4
    assert nd._real_duration(116, 116.3) == 116.3
