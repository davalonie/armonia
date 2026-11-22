import asyncio
import json
import re
from datetime import date, timedelta
from time import perf_counter
from uuid import UUID

from fastapi import HTTPException

import db
from homelab import releases, store


def row(n, kind, age, tracks, today):
    return {"id": str(n), "title": str(n), "type": kind, "date": str(today+timedelta(days=age)),
            "tracks": [{"id": t} for t in tracks]}


def test_window_order_dedup_and_limit():
    now = date(2026, 11, 19)
    rows = [(0, row(0, "Single", -1, ["s"], now)), (1, row(1, "Álbum", -5, ["s"], now)),
            (0, row(2, "EP", -28, ["t"], now)), (0, row(3, "Single", 28, ["u"], now)),
            (0, row(4, "Single", 29, [], now)), (0, row(5, "Single", -29, [], now))]
    assert [x["id"] for x in releases.choose(rows, now)] == ["2", "1", "3"]
    rows.extend((0, row(10+i, "Álbum", -i, [], now)) for i in range(26))
    assert len(releases.choose(rows, now)) == 20


def test_daily_calendar_twenty_artists(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "lab.db")
    monkeypatch.setattr(db, "require_active_session", lambda sess: None)
    monkeypatch.setenv("MUSIC_METADATA_PROXY_ENABLED", "true")
    store.init()
    releases.init()
    names = [f"Grupo {i:02}" for i in range(20)]
    monkeypatch.setattr(releases.generated, "artists", lambda user: [{"name": n} for n in names[15:]])
    now = 1795089600
    with store.connection(write=True) as c:
        for i, name in enumerate(names[:15]):
            event = {"started_at": now-3600, "listened_seconds": 200,
                     "track": {"artist": name, "title": "Siembra", "source": "navidrome", "source_id": str(i)}}
            c.execute("INSERT INTO play_events(owner,id,payload,created) VALUES(?,?,?,?)", ("ana", str(i), json.dumps(event), now))
    calls = []
    async def fake(url, **kwargs):
        calls.append(url)
        q = kwargs["params"].get("query") or kwargs["params"]["q"]
        name = re.search(r"Grupo \d+", q)[0]
        n = names.index(name)
        if n == 19:
            raise HTTPException(503, "simulado")
        key = str(UUID(int=n+1))
        credit = [{"artist": {"name": name}}]
        if "release-group/" in url:
            return {"release-groups": [{"id": key, "title": name, "primary-type": "EP",
                    "artist-credit": credit, "first-release-date": "2026-11-18"}]}
        if "recording/" in url:
            return {"recordings": [{"id": key, "title": name, "artist-credit": credit,
                                    "releases": [{"release-group": {"id": key}}]}]}
        return {"data": []}
    monkeypatch.setattr(releases.integrations, "request_json", fake)
    # Ordinary test uses a virtual provider clock. Set CALENDAR_TIMING=1 for the paced lab run.
    import os
    if os.environ.get("CALENDAR_TIMING") != "1":
        async def musicbrainz(kind, query):
            return await fake(kind+"/", params={"query": query})
        monkeypatch.setattr(releases.metadata, "musicbrainz", musicbrainz)
    async def run():
        start = perf_counter()
        rows = await releases.prepare({}, "ana", now)
        elapsed = perf_counter()-start
        assert len(rows) == 19
        assert all(len(row["tracks"]) == 1 for row in rows)
        # 19 artists × (MusicBrainz release groups, recordings, Deezer search) + the failing one tries both sources.
        assert len(calls) == 59
        assert releases.snapshot("bob")[0] == []
        # The failed provider call is not cached as an empty answer and the calendar is retried within the hour.
        assert releases.snapshot("ana")[1] == now - (releases._DAY - releases._RETRY)
        assert await releases.prepare({}, "ana", now+100) == rows
        assert len(calls) == 61
        print(f"20 artistas, 19 novedades, 1 fallo, 59 consultas simuladas; {elapsed:.2f} s; caché: solo se repite el fallo")
    asyncio.run(run())


def test_opening_only_published_owned_release_resolves_once(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "lab.db")
    monkeypatch.setattr(db, "require_active_session", lambda sess: None)
    store.init()
    releases.init()
    items = [{"id": "new", "date": "2999-01-01", "upcoming": True}, {"id": "old", "date": "2000-01-01", "upcoming": False,
             "tracks": [{"id": "recording", "title": "Ficticia", "artist": "Grupo"}]}]
    with store.connection(write=True) as c:
        c.execute("INSERT INTO release_calendar VALUES(?,?,?)", ("ana", json.dumps(items), 1))
    calls = []

    async def resolve(recording, session, active):
        calls.append(recording["id"])
        return {"id": recording["id"]}, "local"

    monkeypatch.setattr(releases.generated, "resolve_recording", resolve)

    async def open_detail():
        import pytest
        with pytest.raises(HTTPException) as future:
            releases.tracks({}, "ana", "new")
        assert future.value.status_code == 409
        with pytest.raises(HTTPException) as other:
            releases.tracks({}, "otra", "old")
        assert other.value.status_code == 404
        assert releases.tracks({}, "ana", "old")["preparing"]
        assert releases.tracks({}, "ana", "old")["preparing"]
        await asyncio.gather(*releases._resolving.values())
        assert releases.tracks({}, "ana", "old") == {"items": [{"id": "recording"}], "preparing": False}
        assert calls == ["recording"]

    asyncio.run(open_detail())


COVER = "https://cdn-images.dzcdn.net/images/cover/{}/250x250-000000-80-0-0.jpg"


def deezer_lab(monkeypatch, *, albums, details, musicbrainz=None, mb_down=False):
    """Fictitious Deezer and MusicBrainz, shaped like their real answers of 2026-11-21."""
    monkeypatch.setenv("MUSIC_METADATA_PROXY_ENABLED", "true")
    calls = []

    async def request_json(url, **kwargs):
        calls.append(url.removeprefix("https://api.deezer.com/"))
        if url.endswith("search/artist"):
            name = kwargs["params"]["q"]
            return {"data": [{"id": 7, "name": name, "nb_fan": 14403}, {"id": 8, "name": "Haddaway", "nb_fan": 104921}]}
        if url.endswith("artist/7/albums"):
            return {"data": albums}
        number = int(url.rsplit("/", 1)[1])
        return details[number] if number in details else {"error": {"code": 800}}

    async def mb(kind, query):
        calls.append("mb:" + kind + (" título" if "releasegroup:" in query else ""))
        if mb_down:
            raise HTTPException(503, "MusicBrainz saturado")
        return (musicbrainz or {}).get((kind, "releasegroup:" in query), {})

    monkeypatch.setattr(releases.integrations, "request_json", request_json)
    monkeypatch.setattr(releases.metadata, "musicbrainz", mb)
    monkeypatch.setattr(releases, "_next_dz", 0.0)
    return calls


def detail(record_type, artist, tracks):
    return {"record_type": record_type, "artist": {"name": artist}, "contributors": [{"name": artist}],
            "tracks": {"data": [{"id": 100+i, "title": t, "duration": 200, "artist": {"name": artist}} for i, t in enumerate(tracks)]}}


def test_deezer_release_missing_from_musicbrainz_is_found(monkeypatch):
    # The real case: Hard GZ's «LACOSTA 2.5» (18-11-2026) was on Deezer and not on MusicBrainz.
    today = date(2026, 11, 21)
    calls = deezer_lab(monkeypatch, albums=[
        {"id": 1143749781, "title": "LACOSTA 2.5", "release_date": "2026-11-18", "record_type": "album", "cover_medium": COVER.format("ab12")},
        {"id": 906052482, "title": "LACOSTA II", "release_date": "2025-12-04", "record_type": "album"},
    ], details={1143749781: detail("ep", "Hard GZ", ["PLATINO", "LA CORONA", "TODO ESTÁ BIEN", "MONSTRUO"])})
    rows, complete = asyncio.run(releases.fetch_artist("Hard GZ", today))
    assert complete
    [row] = rows
    assert (row["title"], row["type"], row["date"], row["source"]) == ("LACOSTA 2.5", "EP", "2026-11-18", "deezer")
    assert len(row["id"]) == 36 and str(UUID(row["id"])) == row["id"]   # what the 0.6.1 app accepts for covers
    assert row["id"] == asyncio.run(releases.fetch_artist("Hard GZ", today))[0][0]["id"]  # same id every day
    assert row["image"] == COVER.format("ab12")
    assert [t["title"] for t in row["tracks"]] == ["PLATINO", "LA CORONA", "TODO ESTÁ BIEN", "MONSTRUO"]
    assert row["tracks"][0]["duration"] == 200
    assert "album/906052482" not in calls   # outside the 28 days: no detail asked


def test_redated_old_record_is_not_new(monkeypatch):
    # Real: «Mar y Tierra» (2022) is dated 28-01-2026 on Deezer after being uploaded again.
    today = date(2026, 2, 1)
    old = {"release-groups": [{"title": "Mar y Tierra", "first-release-date": "2022-03-24", "primary-type": "Album",
                               "artist-credit": [{"artist": {"name": "Hard GZ"}}]}]}
    deezer_lab(monkeypatch, albums=[{"id": 880365942, "title": "Mar y Tierra", "release_date": "2026-01-28"}],
               details={880365942: detail("album", "Hard GZ", ["Lo Real"])}, musicbrainz={("release-group", True): old})
    assert asyncio.run(releases.fetch_artist("Hard GZ", today)) == ([], True)
    old["release-groups"][0]["first-release-date"] = "2022"   # a year only: still older
    assert asyncio.run(releases.fetch_artist("Hard GZ", today)) == ([], True)


def test_musicbrainz_down_does_not_hide_deezer(monkeypatch):
    today = date(2026, 11, 21)
    deezer_lab(monkeypatch, mb_down=True,
               albums=[{"id": 1143749781, "title": "LACOSTA 2.5", "release_date": "2026-11-18"}],
               details={1143749781: detail("ep", "Hard GZ", ["PLATINO"])})
    rows, complete = asyncio.run(releases.fetch_artist("Hard GZ", today))
    assert [r["title"] for r in rows] == ["LACOSTA 2.5"] and not complete


def test_both_sources_known_once_with_deezer_cover_and_tracks(monkeypatch):
    today = date(2026, 11, 21)
    key = "11111111-1111-4111-8111-111111111111"
    mb = {("release-group", False): {"release-groups": [{"id": key, "title": "EN LA CASA", "primary-type": "Album",
          "first-release-date": "2026-11-03", "artist-credit": [{"artist": {"name": "Foyone", "id": "22222222-2222-4222-8222-222222222222"}}]}]},
          ("recording", False): {"recordings": []}}
    deezer_lab(monkeypatch, musicbrainz=mb, albums=[
        {"id": 5, "title": "En la casa", "release_date": "2026-11-03", "cover_medium": COVER.format("cd34")}],
        details={5: detail("album", "Foyone", ["EL CABRERO", "KETAMINA"])})
    [row] = asyncio.run(releases.fetch_artist("Foyone", today))[0]
    assert row["id"] == key and row["artist_mbid"] and "source" not in row
    assert row["image"] == COVER.format("cd34") and [t["title"] for t in row["tracks"]] == ["EL CABRERO", "KETAMINA"]


def test_other_artist_compilation_and_failed_detail_are_skipped(monkeypatch):
    today = date(2026, 11, 21)
    other = detail("single", "Otro Grupo", ["Algo"])
    deezer_lab(monkeypatch, albums=[{"id": 1, "title": "Ajeno", "release_date": "2026-11-20"},
                                    {"id": 2, "title": "Recopilatorio", "release_date": "2026-11-20"},
                                    {"id": 3, "title": "Sin detalle", "release_date": "2026-11-20"}],
               details={1: other, 2: detail("compile", "Hard GZ", ["X"])})
    assert asyncio.run(releases.fetch_artist("Hard GZ", today)) == ([], False)


def test_metadata_disabled_asks_nobody(monkeypatch):
    calls = deezer_lab(monkeypatch, albums=[], details={})
    monkeypatch.setenv("MUSIC_METADATA_PROXY_ENABLED", "false")
    import pytest
    with pytest.raises(HTTPException):
        asyncio.run(releases.fetch_artist("Hard GZ", date(2026, 11, 21)))
    assert calls == []


def test_pre_release_singles_join_their_record_and_collaborations_come_once():
    today = date(2026, 11, 21)
    def rel(n, kind, artist, title, day, tracks):
        return {"id": n, "type": kind, "artist": artist, "title": title, "date": day,
                "tracks": [{"id": f"{n}-{t}", "title": t} for t in tracks]}
    rows = [(0, rel("a", "Álbum", "Foyone", "EN LA CASA", "2026-11-03", ["El Cabrero", "KETAMINA"])),
            (0, rel("b", "Single", "Foyone", "EL CABRERO", "2026-11-02", ["EL CABRERO"])),
            (0, rel("c", "Single", "Foyone", "KETAMINA", "2026-11-02", ["Ketamina!"])),
            (0, rel("d", "EP", "Hard GZ", "LACOSTA 2.5", "2026-11-18", ["TODO ESTÁ BIEN"])),
            (0, rel("e", "Single", "Hard GZ", "TODO ESTÁ BIEN", "2026-11-18", ["TODO ESTÁ BIEN"])),
            (0, rel("f", "Single", "Natos y Waor", "MI VIDA", "2026-11-13", ["MI VIDA"])),
            (1, rel("g", "Single", "Recycled J", "MI VIDA", "2026-11-13", ["MI VIDA"])),
            # Same title and day from another artist is the same collaboration (real: Midas Alonso, «EL CABRERO»).
            (0, rel("h", "Single", "Midas Alonso", "EL CABRERO", "2026-11-02", ["EL CABRERO"])),
            # Another artist's song with the same title on another day is a different song.
            (0, rel("i", "Single", "Otro", "El Cabrero", "2026-11-09", ["El Cabrero"]))]
    assert sorted(r["id"] for r in releases.choose(rows, today)) == ["a", "d", "f", "i"]


def test_release_already_in_library_is_left_out(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "lab.db")
    monkeypatch.setattr(db, "require_active_session", lambda sess: None)
    store.init()
    releases.init()
    now = 1795089600
    with store.connection(write=True) as c:
        event = {"started_at": now-3600, "listened_seconds": 200,
                 "track": {"artist": "Hard GZ", "title": "Siembra", "source": "navidrome", "source_id": "1"}}
        c.execute("INSERT INTO play_events(owner,id,payload,created) VALUES(?,?,?,?)", ("ana", "1", json.dumps(event), now))
    monkeypatch.setattr(releases.generated, "artists", lambda user: [])
    day = str(date.fromtimestamp(now) - timedelta(days=2))
    deezer_lab(monkeypatch, albums=[{"id": 1, "title": "Ya la tengo", "release_date": day},
                                    {"id": 2, "title": "Nueva", "release_date": day}],
               details={1: detail("ep", "Hard GZ", ["Uno"]), 2: detail("ep", "Hard GZ", ["Dos"])})
    async def library(query, sess):
        return [{"album": "Ya la tengo", "artist": "Hard GZ", "title": "Uno"}] if query == "Ya la tengo" else []
    monkeypatch.setattr(releases.generated, "_local_songs", library)
    rows = asyncio.run(releases.prepare({"username": "ana"}, "ana", now))
    assert [r["title"] for r in rows] == ["Nueva"]
