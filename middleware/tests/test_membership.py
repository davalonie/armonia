import json
from time import perf_counter
from urllib.parse import parse_qs

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

import db
from auth import get_current_session
from routes import membership
from services import navidrome_client as nd


def test_player_index_and_duplicate_removal(monkeypatch):
    routes = []
    changes = []
    own = [{"id": f"list-{i}", "owner": "ana", "songCount": 2000, "changed": "1"} for i in range(30)]
    own[0].pop("changed")  # Older responses can have only the count.
    songs = [{"id": f"song-{i}", "title": f"Grabación {i}", "artist": "Grupo de laboratorio",
              "duration": 210, "album": "Laboratorio"} for i in range(1999)] + [{"id": "song-0"}]

    def upstream(request):
        verb = request.url.path.rsplit("/", 1)[1]
        routes.append(verb)
        pairs = parse_qs(request.content.decode())
        if verb == "getPlaylists":
            value = {"playlists": {"playlist": own + [{"owner": "bob", "id": "private"}]}}
        elif verb == "getPlaylist":
            updated = any(c["playlistId"] == pairs["id"] for c in changes)
            entries = [s for s in songs if s["id"] != "song-0"] if updated else songs
            value = {"playlist": {"owner": "bob" if pairs["id"] == ["private"] else "ana", "entry": entries}}
        elif verb == "getSong":
            value = {"song": {"id": "song-0"}}
        else:
            changes.append(pairs)
            value = {}
        return httpx.Response(200, json={"subsonic-response": {"status": "ok", **value}})

    monkeypatch.setattr(nd, "_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(upstream), **kw))
    monkeypatch.setattr(db, "require_active_session", lambda sess: None)
    monkeypatch.setattr(membership, "_indices", membership.OrderedDict())
    app = FastAPI()
    app.include_router(membership.router)
    app.dependency_overrides[get_current_session] = lambda: dict(user_id="fixture", username="ana", salt="fixture", token="fixture")
    client = TestClient(app)
    times = []
    for _ in range(12):
        start = perf_counter()
        response = client.get("/api/playlists/membership?song=song-0&summary=true")
        times.append((perf_counter()-start)*1000)
        assert response.json() == {"saved": True}
    assert routes.count("getPlaylist") == 30
    headers = sum(len(k)+len(v)+4 for k,v in response.headers.items())+19
    print(f"Fixture 30x2000; cold={times[0]:.1f} ms; warm max={max(times[1:]):.1f} ms; "
          f"body={len(response.content)} B; HTTP/1.1 estimated={headers+len(response.content)} B")
    full = client.get("/api/playlists/membership?song=song-0").json()
    assert len(full["playlists"]) == 30 and "private" not in full["playlists"]
    selection = {"song": "song-0", "included": False}
    assert client.put("/api/playlists/private/membership", json=selection).status_code == 403
    assert client.put("/api/playlists/list-1/membership", json=selection).is_success
    assert changes == [{"playlistId": ["list-1"], "songIndexToRemove": ["1999", "0"]}]
    refreshed = client.get("/api/playlists/membership?song=song-0").json()
    assert len(refreshed["playlists"]) == 29 and "list-1" not in refreshed["playlists"]
    assert len(json.dumps(full)) < 1024


def test_a_song_not_in_the_library_is_refused_instead_of_silently_dropped(monkeypatch):
    # Before 0.6 a not-yet-downloaded song ("preview|<video>") was sent on to Navidrome, which dropped it:
    # the reply was 200 and the playlist stayed the same. Now nothing reaches Navidrome and the app is told.
    from routes import playlist_edit
    calls = []

    def upstream(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"subsonic-response": {"status": "ok", "playlist": {"owner": "ana", "entry": [{"id": "song-0"}]}}})

    monkeypatch.setattr(nd, "_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(upstream), **kw))
    monkeypatch.setattr(db, "require_active_session", lambda sess: None)
    app = FastAPI()
    app.include_router(membership.router)
    app.include_router(playlist_edit.router)
    app.dependency_overrides[get_current_session] = lambda: dict(user_id="fixture", username="ana", salt="fixture", token="fixture")
    client = TestClient(app)
    for song in ("preview|aBcDeFgHiJk", "external|ficticia"):
        assert client.put("/api/playlists/list-1/membership", json={"song": song, "included": True}).status_code == 422
        edit = {"expected": ["song-0"], "songs": ["song-0", song]}
        assert client.post("/api/playlists/list-1/edit", json=edit).status_code == 422
    assert calls == []
    # Library songs still go through, removals included.
    assert client.post("/api/playlists/list-1/edit", json={"expected": ["song-0"], "songs": ["song-0"]}).json() == {"count": 1}
    assert client.put("/api/playlists/list-1/membership", json={"song": "song-0", "included": True}).json() == {"ok": True}


def test_deleting_a_song_forgets_the_saved_answer(monkeypatch, tmp_path):
    """Navidrome hides a deleted song from its playlists without changing their stamps: the ✓ must not stay."""
    import asyncio

    from routes import tracks

    monkeypatch.setattr(db, "require_active_session", lambda sess: None)
    monkeypatch.setattr(membership, "_indices", membership.OrderedDict())
    stale = membership._indices.setdefault("ana", membership.Index())
    stale.replace("list-1", {"song-0"}, ("1", 1))
    other = membership._indices.setdefault("bob", membership.Index())

    def upstream(request):
        return httpx.Response(200, json={"subsonic-response": {"status": "ok", "song": {"id": "song-0", "title": "Ficticia",
                                                                                         "path": "Grupo/Ficticia.m4a"}}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(tracks.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(upstream), **kw))
    monkeypatch.setattr(tracks, "DELETE_USERS", {"ana"})

    async def yes(*args, **kwargs):
        return True

    async def library(sess):
        return 1

    async def scanned(*args, **kwargs):
        return None

    monkeypatch.setattr(tracks.navidrome_client, "is_admin", yes)
    monkeypatch.setattr(tracks.navidrome_client, "require_library_access", library)
    monkeypatch.setattr(tracks.navidrome_client, "scan_until", scanned)
    monkeypatch.setattr(tracks.navidrome_client, "scan_target", lambda *args: None)
    monkeypatch.setattr(tracks.safe_files, "library_root", lambda *args: tmp_path)
    monkeypatch.setattr(tracks.safe_files, "unlink_music", lambda root, path: tmp_path / path)
    monkeypatch.setattr(tracks, "owner", lambda sess: sess["username"])
    monkeypatch.setattr(tracks.db, "active_session", lambda sess: __import__("contextlib").nullcontext())
    sess = dict(user_id="fixture", username="ana", salt="fixture", token="fixture", is_admin=True, library_path=None)
    assert asyncio.run(tracks.delete_track("song-0", sess)) == {"ok": True}
    assert "ana" not in membership._indices
    assert membership._indices["bob"] is other
