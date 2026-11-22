"""«Continuar con música similar»: per-user setting and a bounded, private batch of related songs."""
import random

import pytest
from fastapi import HTTPException

import db
from homelab import continuation, store
from homelab import generated_playlists as g
from routes import home
from routes.home import Continue, Settings


def song(n, artist):
    return {"id": f"i{n}", "cover": None,
            "track": {"source": "youtube", "source_id": f"vid{n:08d}", "title": f"T{n}", "artist": artist, "album": "", "duration": 200.0}}


@pytest.fixture
def users(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "armonia.db")
    db.init_db()
    store.init()
    g.init()
    g._write("alice", "weekly", "Armonía semanal", "", [song(n, "Ana") for n in range(1, 5)] + [song(5, "Rita")], "ready")
    g._write("alice", "similar:a466063b-24a6-4235-bc95-352c93d8ce47", "Mix Semilla", "",
             [song(n, "Beta, Gamma") for n in range(6, 9)] + [song(9, "Delta")], "ready")
    g._write("alice", "@status", "", "", [], "ready")
    return {u: db.get_session(db.create_session(u, "s", "t", user_id=u)) for u in ("alice", "bob")}


def ids(result):
    return [i["track"]["source_id"] for i in result["items"]]


def test_setting_is_on_by_default_and_private_to_each_user(users):
    assert home.settings(users["alice"]) == {"continue_similar": True}
    home.write_settings(Settings(continue_similar=False), users["alice"])
    assert home.settings(users["alice"]) == {"continue_similar": False}
    assert home.settings(users["bob"]) == {"continue_similar": True}
    # Switched off: the server offers nothing, whatever an old client asks.
    assert home.continue_similar(Continue(artists=["Ana"]), users["alice"]) == {"enabled": False, "items": []}
    home.write_settings(Settings(continue_similar=True), users["alice"])
    assert home.continue_similar(Continue(), users["alice"])["items"]


def test_batch_is_small_related_first_without_repeats_or_excluded_songs(users):
    first = home.continue_similar(Continue(artists=["Semilla"]), users["alice"])
    assert first["enabled"] and len(first["items"]) == continuation.BATCH
    assert len(set(ids(first))) == len(ids(first))
    # The mix about the artist just heard comes first; no more than two songs by one credit.
    assert set(ids(first)[:3]) <= {f"vid{n:08d}" for n in range(6, 10)}
    assert sum(i["track"]["artist"] == "Beta, Gamma" for i in first["items"]) == 2
    heard = [f"youtube:{v}" for v in ids(first)]
    second = home.continue_similar(Continue(artists=["Semilla"], exclude=heard), users["alice"])
    assert not set(ids(second)) & set(ids(first))
    everything = [f"youtube:vid{n:08d}" for n in range(1, 10)]
    assert home.continue_similar(Continue(exclude=everything), users["alice"])["items"] == []


def test_a_collaborator_of_the_song_just_heard_counts_as_related(users):
    picked = continuation.batch("alice", ["Gamma feat. Otro"], set(), rng=random.Random(1))
    assert picked[0]["track"]["artist"] in {"Beta, Gamma", "Delta"}


def test_another_user_gets_nothing_from_these_lists_and_nothing_is_written(users):
    before = g.summaries("alice")
    assert home.continue_similar(Continue(artists=["Ana"]), users["bob"]) == {"enabled": True, "items": []}
    assert g.summaries("alice") == before and g.summaries("bob") == []
    assert store.playlists("alice") == [] and store.playlists("bob") == []


def test_a_revoked_session_gets_no_songs_and_cannot_change_the_setting(users):
    db.delete_session(users["alice"]["id"])
    with pytest.raises(HTTPException):
        home.continue_similar(Continue(), users["alice"])
    with pytest.raises(HTTPException):
        home.write_settings(Settings(continue_similar=False), users["alice"])
