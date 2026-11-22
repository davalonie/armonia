import asyncio
import json
import time
from uuid import uuid4

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
    d._refresh_locks.clear()
    monkeypatch.setattr(d, "_network", asyncio.Semaphore(2))

    async def no_preferences(user):
        return []

    monkeypatch.setattr(d, "preferences", no_preferences)
    return tmp_path


def event(user, name, title="A distinct song", ids=None, ident=None):
    ident = ident or str(uuid4())
    data = {"track": {"artist": name, "title": title, "artist_mbids": ids or []}}
    with store.connection(write=True) as c:
        c.execute("INSERT INTO play_events VALUES (?,?,?,?,?)", (user, ident, json.dumps(data), int(time.time()), None))
    return ident


def run(work):
    return asyncio.run(work)


def providers(monkeypatch, users):
    async def ranking(user, **kw):
        return {
            "items": [
                {"item": {"id": i + 1, "name": name, "musicbrainz_id": mbid}}
                for i, (name, mbid) in enumerate(users[user])
            ]
        }

    async def similar(user, path, *args):
        assert path.startswith("/api/artists/") and "/similar?" in path
        return {"artists": [{"name": "Similar " + user, "id": B, "image": "private-image", "secret": "never expose"}]}

    monkeypatch.setattr(integrations, "koito_read", ranking)
    monkeypatch.setattr(integrations, "aurral_request", similar)


def test_two_users_verified_and_no_mbid_real_pipeline(lab, monkeypatch):
    providers(monkeypatch, {"alice": [("Alpha", None)], "bob": [("Beta", B)]})
    event("alice", "Alpha")
    calls = []

    async def mb(kind, query):
        calls.append((kind, query))
        if kind == "artist":
            return {"artists": [{"name": "Alpha", "id": A}]}
        return {"recordings": [{"title": "A distinct song", "artist-credit": [{"artist": {"id": A}}]}]}

    monkeypatch.setattr(d, "musicbrainz", mb)
    for user in ("alice", "bob"):
        data = run(d.recommendations(user))
        assert data["artists"][0]["name"] == "Similar " + user
        assert data["artists"][0]["sourceArtist"] == ("Alpha" if user == "alice" else "Beta")
        assert data["artists"][0]["provenance"] == "similar_to_identified_seed"
        assert data["general"] == [] and "secret" not in json.dumps(data)
    assert len(calls) == 2 and all("alice" not in q and "bob" not in q for _, q in calls)

    async def fail(*a, **kw):
        raise AssertionError("cache missed")

    monkeypatch.setattr(integrations, "aurral_request", fail)
    assert run(d.recommendations("alice"))["state"] == "ready"


def test_ambiguous_name_not_first_result_and_corroborated_homonym(lab, monkeypatch):
    event("alice", "Same name", "Known song")

    async def mb(kind, query):
        if kind == "artist":
            return {"artists": [{"name": "Same name", "id": C}, {"name": "Same name", "id": B}]}
        return {"recordings": [{"title": "Known song", "artist-credit": [{"artist": {"id": B}}]}]}

    monkeypatch.setattr(d, "musicbrainz", mb)
    assert run(d.identify("alice", {"name": "Same name"}))["mbid"] == B
    assert run(d.identify("bob", {"name": "Same name"}))["status"] == "ambiguous"


def test_only_name_is_not_identity_and_conflicting_ids(lab, monkeypatch):
    async def mb(*a):
        return {"artists": [{"name": "Alpha", "id": A}]}

    monkeypatch.setattr(d, "musicbrainz", mb)
    assert run(d.identify("alice", {"name": "Alpha"}))["mbid"] is None
    event("bob", "Alpha", ids=[A])
    event("bob", "Alpha", ids=[B])
    assert run(d.identify("bob", {"name": "Alpha"}))["reason"] == "conflicting_ids"


def test_metadata_failure_negative_expiry_and_retry(lab, monkeypatch):
    event("alice", "Alpha")

    async def fail(*args):
        raise HTTPException(502, "private upstream body")

    monkeypatch.setattr(d, "musicbrainz", fail)
    result = run(d.identify("alice", {"name": "Alpha"}))
    assert result["status"] == "unavailable" and "private" not in json.dumps(result)

    async def good(kind, query):
        return (
            {"artists": [{"name": "Alpha", "id": A}]}
            if kind == "artist"
            else {"recordings": [{"title": "A distinct song", "artist-credit": [{"artist": {"id": A}}]}]}
        )

    monkeypatch.setattr(d, "musicbrainz", good)
    assert run(d.identify("alice", {"name": "Alpha"}))["status"] == "unavailable"
    with store.connection(write=True) as c:
        c.execute("UPDATE discovery_identity SET expires=0")
    assert run(d.identify("alice", {"name": "Alpha"}))["status"] == "identified"
    d.invalidate("alice", "Alpha")
    with store.connection() as c:
        assert c.execute("SELECT count(*) FROM discovery_identity").fetchone()[0] == 0


@pytest.mark.parametrize("names", [[], [("Synthetic", A)]])
def test_empty_or_only_synthetic_profile_never_uses_trends(lab, monkeypatch, names):
    providers(monkeypatch, {"alice": names})
    file = lab / "quarantine.json"
    file.write_text(json.dumps({"users": {"alice": {"artists": [{"id": 1, "name": "Synthetic"}]}}}))
    monkeypatch.setenv("MUSIC_DISCOVERY_QUARANTINE_FILE", str(file))
    result = run(d.recommendations("alice"))
    assert result["artists"] == [] and result["state"] == "insufficient_profile" and result["seeds"] == []


def test_mixed_profile_exact_quarantine_before_and_after_cleanup(lab, monkeypatch):
    providers(monkeypatch, {"alice": [("Synthetic", A), ("Real", B)], "bob": [("Synthetic", C)]})
    file = lab / "quarantine.json"
    file.write_text(json.dumps({"users": {"alice": {"artists": [{"id": 1, "name": "Synthetic"}]}}}))
    monkeypatch.setenv("MUSIC_DISCOVERY_QUARANTINE_FILE", str(file))
    first = run(d.recommendations("alice"))
    assert [s["name"] for s in first["seeds"]] == ["Real"]
    assert run(d.recommendations("bob"))["seeds"][0]["name"] == "Synthetic"
    providers(monkeypatch, {"alice": [("Real", B)]})
    assert run(d.recommendations("alice")) == first


def test_aurral_outage_and_recovery_no_cached_trends(lab, monkeypatch):
    providers(monkeypatch, {"alice": [("Real", A)]})

    async def fail(*args):
        raise HTTPException(502, "provider failed")

    monkeypatch.setattr(integrations, "aurral_request", fail)
    result = run(d.recommendations("alice"))
    assert result["state"] == "unavailable" and not result["artists"]
    providers(monkeypatch, {"alice": [("Real", A)]})
    d.invalidate("alice")
    assert run(d.recommendations("alice"))["state"] == "ready"


def test_cache_invalidation_scoped_and_context_changes(lab, monkeypatch):
    providers(monkeypatch, {"alice": [("Real", A)], "bob": [("Other", B)]})
    for user in ["alice", "bob"]:
        run(d.recommendations(user))
    d.invalidate("alice")
    with store.connection() as c:
        assert [r[0] for r in c.execute("SELECT owner FROM discovery_personal")] == ["bob"]
    event("alice", "Real", ids=[B])
    assert run(d.recommendations("alice"))["seeds"][0]["status"] == "ambiguous"


def test_injection_escaped_and_fuzzy_titles_not_evidence(lab, monkeypatch):
    assert '\\"' in d.literal('A" OR *:*')
    event("alice", "Real", "Known Song")

    async def mb(kind, q):
        return (
            {"artists": [{"name": "Real", "id": A}]}
            if kind == "artist"
            else {"recordings": [{"title": "Known Song live", "artist-credit": [{"artist": {"id": A}}]}]}
        )

    monkeypatch.setattr(d, "musicbrainz", mb)
    assert run(d.identify("alice", {"name": "Real"}))["mbid"] is None


def test_fixture_references_never_reenter_live_outbox(lab, monkeypatch):
    from homelab import listening

    path = lab / "quarantine.json"
    path.write_text(json.dumps({"fixture_references": [["authorized_http", "tone"]]}))
    monkeypatch.setenv("MUSIC_DISCOVERY_QUARANTINE_FILE", str(path))
    ev = listening.Listen(
        id=uuid4(),
        started_at=int(time.time()) - 100,
        listened_seconds=20,
        track={
            "source": "authorized_http",
            "source_id": "tone",
            "title": "Anything",
            "artist": "Anything",
            "duration": 34,
        },
    )
    assert listening.accept("alice", ev)["ignored"] == "laboratory_reference"
    with store.connection() as c:
        assert c.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0


def test_cancelled_slow_refresh_releases_lock(lab, monkeypatch):
    providers(monkeypatch, {"alice": [("Real", A)]})
    entered = asyncio.Event()

    async def slow(*args):
        entered.set()
        await asyncio.sleep(100)

    monkeypatch.setattr(integrations, "aurral_request", slow)

    async def scenario():
        task = asyncio.create_task(d.recommendations("alice"))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert all(not lock.locked() for lock in d._refresh_locks.values())

    run(scenario())


def test_revoked_session_cannot_receive_slow_result_or_snapshot(lab, monkeypatch):
    from routes import discover

    db.init_db()
    sid = db.create_session("alice", "s", "t", user_id="alice")
    sess = db.get_session(sid)

    async def result(user):
        db.delete_session(sid)
        return {"version": 1, "artists": [], "seeds": [], "state": "insufficient_profile"}

    monkeypatch.setattr(d, "recommendations", result)
    with pytest.raises(HTTPException) as exc:
        run(discover.discover(sess))
    assert exc.value.status_code == 401
    with store.connection() as c:
        assert c.execute("SELECT count(*) FROM recommendations").fetchone()[0] == 0


def test_old_snapshots_hidden_without_deleting_saved_playlists(lab):
    from routes import discover

    with store.connection(write=True) as c:
        c.execute(
            "INSERT INTO recommendations VALUES (?,?,?,?)",
            ("old", "alice", 1, json.dumps({"artists": [{"name": "Chart"}]})),
        )
        c.execute(
            "INSERT INTO recommendations VALUES (?,?,?,?)", ("new", "bob", 2, json.dumps({"version": 1, "artists": []}))
        )
    assert discover.history({"user_id": "alice"})["snapshots"] == []
    assert len(discover.history({"user_id": "bob"})["snapshots"]) == 1
    with store.connection() as c:
        assert c.execute("SELECT count(*) FROM recommendations").fetchone()[0] == 2


def test_musicbrainz_retries_transient_failure_once_with_metadata_only(lab, monkeypatch):
    monkeypatch.setenv("MUSIC_METADATA_PROXY_ENABLED", "true")
    monkeypatch.setattr(d, "_mb_lock", asyncio.Lock())
    monkeypatch.setattr(d, "_next_mb", 0)
    calls = []

    async def request(url, **kwargs):
        calls.append(kwargs["params"])
        if len(calls) == 1:
            raise HTTPException(502, "temporary failure")
        return {"artists": []}

    monkeypatch.setattr(integrations, "request_json", request)
    assert run(d.musicbrainz("artist", 'artist:"Fictional"')) == {"artists": []}
    assert len(calls) == 2 and calls[0] == {"query": 'artist:"Fictional"', "fmt": "json", "limit": 25}


def test_lastfm_empty_or_swallowed_failure_expires_without_chart_fallback(lab, monkeypatch):
    providers(monkeypatch, {"alice": [("Real", A)]})

    async def empty(*args):
        return {"artists": []}  # Native Aurral also uses this for unavailable Last.fm.

    monkeypatch.setattr(integrations, "aurral_request", empty)
    result = run(d.recommendations("alice"))
    assert result["state"] == "no_similar_results" and result["artists"] == []
    with store.connection(write=True) as c:
        assert c.execute("SELECT expires FROM discovery_personal").fetchone()[0] <= time.time() + 60
        c.execute("UPDATE discovery_personal SET expires=0")
    providers(monkeypatch, {"alice": [("Real", A)]})
    assert run(d.recommendations("alice"))["state"] == "ready"


def test_manual_exclusions_invalidate_only_their_users_cache(lab, monkeypatch):
    providers(monkeypatch, {"alice": [("Seed", A)], "bob": [("Other", B)]})
    assert run(d.recommendations("alice"))["artists"]
    assert run(d.recommendations("bob"))["artists"]

    async def preferences(user):
        return [{"action": "block_artist", "artistName": "Similar alice"}] if user == "alice" else []

    monkeypatch.setattr(d, "preferences", preferences)
    assert run(d.recommendations("alice"))["artists"] == []
    assert run(d.recommendations("bob"))["artists"][0]["name"] == "Similar bob"
