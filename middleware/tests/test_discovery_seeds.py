"""Seed identification against simulated MusicBrainz answers: credits of several artists, aliases and the
503 + Retry-After with which MusicBrainz sheds load. Never a guess: a name alone identifies nobody."""
import asyncio
import json
import time

import httpx
import pytest
from fastapi import HTTPException

import db
from homelab import discovery_profile as d
from homelab import integrations, store

A = "a466063b-24a6-4235-bc95-352c93d8ce47"
B = "3aa9e7cd-fe96-4fea-b200-19beeea963c7"
C = "dc4d5a7d-dfd8-4f0e-97bb-311f7e3a7edc"


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "armonia.db")
    store.init()
    d.init()
    monkeypatch.delenv("MUSIC_DISCOVERY_QUARANTINE_FILE", raising=False)
    monkeypatch.setattr(d, "_network", asyncio.Semaphore(2))
    return tmp_path


def event(user, artist, title, ids=()):
    data = {"track": {"artist": artist, "title": title, "artist_mbids": list(ids)}}
    with store.connection(write=True) as c:
        c.execute("INSERT INTO play_events VALUES (?,?,?,?,?)", (user, title + artist, json.dumps(data), int(time.time()), None))


def run(work):
    return asyncio.run(work)


@pytest.mark.parametrize("name,expected", [
    ("EAZYBOI, ToteKing", ["EAZYBOI", "ToteKing"]),
    ("Alpha feat. Beta", ["Alpha", "Beta"]),
    ("Alpha ft. Beta, Gamma", ["Alpha", "Beta", "Gamma"]),
    ("Alpha, alpha", ["Alpha"]),
    # «y» and «&» are part of band names: never split without corroboration (matcher.credits).
    ("Rade y Mala Praxis", ["Rade y Mala Praxis"]),
    ("Charlie Hijos Bastardos", ["Charlie Hijos Bastardos"]),
    ("Simon & Garfunkel", ["Simon & Garfunkel"]),
])
def test_seed_names_split_as_matcher_credits(name, expected):
    assert d.seed_names(name) == expected


def musicbrainz(artists, recordings, calls):
    async def mb(kind, query):
        calls.append((kind, query))
        if kind == "artist":
            name = query.split('"')[1]
            return {"artists": artists.get(name, [])}
        return {"recordings": recordings}
    return mb


def test_credit_entry_gives_each_artist_and_alias_is_backed_by_a_recording(lab, monkeypatch):
    # Koito lists the whole credit as one artist; the songs carry both IDs (no single name -> ID mapping).
    event("alice", "EAZYBOI, ToteKing", "Shared song", ids=[A, B])

    async def ranking(user, **kw):
        return {"items": [{"item": {"id": 1, "name": "EAZYBOI, ToteKing", "musicbrainz_id": C}}]}

    calls = []
    artists = {
        "EAZYBOI": [{"name": "EAZIBOY", "id": A, "aliases": [{"name": "EazyBoi"}]}],
        "ToteKing": [{"name": "ToteKing", "id": B, "aliases": [{"name": "Tote King"}]}],
    }
    recordings = [{"title": "Shared song", "artist-credit": [
        {"artist": {"id": A, "name": "EAZIBOY"}}, {"artist": {"id": B, "name": "ToteKing"}}]}]
    monkeypatch.setattr(integrations, "koito_read", ranking)
    monkeypatch.setattr(d, "musicbrainz", musicbrainz(artists, recordings, calls))
    seeds = run(d.profile("alice"))
    assert [(s["name"], s["status"], s["mbid"]) for s in seeds] == [
        ("EAZYBOI", "identified", A), ("ToteKing", "identified", B)]
    # Koito's MBID of the whole credit is given to neither; aliases are asked for, and recordings by ID.
    assert ("artist", 'artist:"EAZYBOI" OR alias:"EAZYBOI"') in calls
    assert ("recording", f'(artist:"EAZYBOI" OR arid:{A}) AND recording:"Shared song"') in calls


def test_alias_without_a_heard_recording_identifies_nobody(lab, monkeypatch):
    calls = []
    monkeypatch.setattr(d, "musicbrainz", musicbrainz(
        {"EAZYBOI": [{"name": "EAZIBOY", "id": A, "aliases": [{"name": "EazyBoi"}]}]}, [], calls))
    result = run(d.identify("alice", {"name": "EAZYBOI"}))
    assert result["status"] == "unresolved" and result["mbid"] is None


def test_name_and_alias_of_two_artists_with_the_same_song_stay_ambiguous(lab, monkeypatch):
    event("alice", "Same", "Known song")
    calls = []
    monkeypatch.setattr(d, "musicbrainz", musicbrainz(
        {"Same": [{"name": "Same", "id": A}, {"name": "Other", "id": B, "aliases": [{"name": "SAME"}]}]},
        [{"title": "Known song", "artist-credit": [{"artist": {"id": A}}]},
         {"title": "Known song", "artist-credit": [{"artist": {"id": B}}]}], calls))
    result = run(d.identify("alice", {"name": "Same"}))
    assert result["status"] == "ambiguous" and result["mbid"] is None


def test_partial_alias_or_similar_name_is_not_a_candidate(lab, monkeypatch):
    event("alice", "Charlie Hijos Bastardos", "Known song")
    calls = []
    monkeypatch.setattr(d, "musicbrainz", musicbrainz(
        {"Charlie Hijos Bastardos": [{"name": "Hijos Bastardos", "id": A, "aliases": [{"name": "Los Hijos Bastardos"}]}]},
        [{"title": "Known song", "artist-credit": [{"artist": {"id": A}}]}], calls))
    result = run(d.identify("alice", {"name": "Charlie Hijos Bastardos"}))
    assert result["reason"] == "not_found" and result["mbid"] is None


def test_local_context_titles_from_shared_credits_ids_only_from_own_songs(lab):
    event("alice", "EAZYBOI, ToteKing", "Shared", ids=[A, B])
    event("alice", "ToteKing", "Alone", ids=[B])
    event("alice", "ToteKingdom", "Other", ids=[C])
    assert d.local_context("alice", "ToteKing") == (["Alone", "Shared"], [B])
    assert d.local_context("alice", "EAZYBOI") == (["Shared"], [])


def shed(retry_after="1"):
    response = httpx.Response(503, headers={"Retry-After": retry_after}, request=httpx.Request("GET", "https://mb.test"))
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as cause:
        error = HTTPException(502, "linked music service unavailable")
        error.__cause__ = cause
        return error


@pytest.fixture
def mb_clock(lab, monkeypatch):
    monkeypatch.setenv("MUSIC_METADATA_PROXY_ENABLED", "true")
    monkeypatch.setattr(d, "_mb_lock", asyncio.Lock())
    monkeypatch.setattr(d, "_next_mb", 0)
    waits = []
    real_sleep = asyncio.sleep

    async def sleep(seconds):
        waits.append(round(seconds, 1))
        await real_sleep(0)

    monkeypatch.setattr(d.asyncio, "sleep", sleep)
    return waits


def test_musicbrainz_waits_as_asked_when_it_sheds_load(mb_clock, monkeypatch):
    answers = [shed("1"), shed("3"), shed("60"), {"artists": []}]

    async def request(url, **kwargs):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(integrations, "request_json", request)
    assert run(d.musicbrainz("artist", 'artist:"Fictional"')) == {"artists": []}
    # 1.1 s at least (one request per second), Retry-After honoured, never more than 5 s.
    assert [w for w in mb_clock if w] == [1.1, 3.0, 5.0]


def test_musicbrainz_gives_up_after_four_sheds_and_identify_says_unavailable(mb_clock, monkeypatch):
    calls = []

    async def request(url, **kwargs):
        calls.append(kwargs["params"]["query"])
        raise shed()

    monkeypatch.setattr(integrations, "request_json", request)
    event("alice", "Alpha", "Song")
    result = run(d.identify("alice", {"name": "Alpha"}))
    assert len(calls) == d.MB_ATTEMPTS == 4
    assert result["status"] == "unavailable" and result["reason"] == "metadata_unavailable"


def test_other_upstream_failures_still_retry_only_once(mb_clock, monkeypatch):
    calls = []

    async def request(url, **kwargs):
        calls.append(1)
        raise HTTPException(502, "linked music service unavailable")

    monkeypatch.setattr(integrations, "request_json", request)
    with pytest.raises(HTTPException):
        run(d.musicbrainz("artist", 'artist:"Fictional"'))
    assert len(calls) == 2
