import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import db
from auth import get_current_session
from homelab import matcher, sources, store
from homelab.models import PlaylistWrite, Track
from routes import mixed_playlists
from routes.tracks import _safe_stream


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "armonia.db")
    store.init()
    app = FastAPI()
    app.include_router(mixed_playlists.router)
    c = TestClient(app)
    def as_user(user):
        app.dependency_overrides[get_current_session] = lambda: {"user_id": user, "username": user, "salt": "s", "token": "t"}
    c.as_user = as_user
    c.as_user("alice-id")
    return c


def track(title="Song", artist="Artist", duration=200, **kwargs):
    return Track(source="authorized_http", source_id="one", title=title, artist=artist, duration=duration, **kwargs)


def test_upgrade_v1_keeps_private_playlists_and_outbox(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'armonia.db')
    ident = '11111111-1111-4111-8111-111111111111'
    payload = json.dumps({'track': {'title': 'Song', 'artist': 'Artist', 'artist_mbids': [ident]}})
    with sqlite3.connect(tmp_path / 'music.db') as c:
        c.executescript(store._SCHEMA + 'PRAGMA user_version=1;')
        c.execute('INSERT INTO playlists VALUES (?,?,?,?,?,?)', ('original', 'alice', 'Keep me', 7, '[]', 1))
        c.execute('INSERT INTO play_events VALUES (?,?,?,?)', ('alice', 'event', payload, 1))
        c.execute("INSERT INTO outbox(owner,event_id,destination) VALUES ('alice','event','koito')")
    store.init()
    store.init()
    assert store.playlist('alice', 'original')['revision'] == 7
    with pytest.raises(HTTPException):
        store.playlist('bob', 'original')
    with store.connection() as c:
        assert c.execute('PRAGMA user_version').fetchone()[0] == 4
        assert c.execute('SELECT payload FROM play_events').fetchone()[0] == payload
        assert c.execute('SELECT count(*) FROM outbox').fetchone()[0] == 1
        assert tuple(c.execute('SELECT * FROM artist_identities').fetchone()) == ('alice', 'artist', ident)
        c.execute('PRAGMA user_version=5')
    with pytest.raises(RuntimeError, match='newer'):
        store.init()


def test_matching_never_automatically_selects_nearly_identical_long_title_or_album_version():
    original = track(title="A very long song title ending with one", album="Studio")
    changed = track(title="A very long song title ending with two", album="Studio")
    assert matcher.rank(original, [changed])["selected"] is None
    assert matcher.rank(original, [track(title=original.title, album="Live in London")])["selected"] is None


def body(revision=0):
    return {"name": "My mixed playlist", "revision": revision, "items": [
        {"id": str(uuid4()), "track": track().model_dump(mode="json")},
        {"id": str(uuid4()), "track": {**track().model_dump(mode="json"), "source": "navidrome", "source_id": "local"}},
    ]}


def test_playlist_roundtrip_reorder_duplicates_and_restart(client):
    p = client.post("/api/mixed-playlists", json=body()).json()
    assert p["revision"] == 1 and len(p["items"]) == 2
    # Same recording twice is legal; entry IDs still distinguish them.
    p["items"].append({"id": str(uuid4()), "track": p["items"][0]["track"]})
    p["items"].reverse()
    update = {k: p[k] for k in ("name", "revision", "items")}
    saved = client.put(f'/api/mixed-playlists/{p["id"]}', json=update)
    assert saved.status_code == 200 and saved.json()["items"] == p["items"]
    store.init()
    again = client.get(f'/api/mixed-playlists/{p["id"]}').json()
    assert again["revision"] == 2 and len(again["items"]) == 3
    with store.connection() as c:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_playlist_cross_user_access_is_denied_in_all_routes(client):
    p = client.post("/api/mixed-playlists", json=body()).json()
    client.as_user("bob-id")
    url = f'/api/mixed-playlists/{p["id"]}'
    assert client.get("/api/mixed-playlists").json() == {"playlists": []}
    assert client.get(url).status_code == 404
    assert client.put(url, json=body(1)).status_code == 404
    assert client.delete(url, params={"revision": 1}).status_code == 404
    assert client.post(url + "/export-navidrome", json={"revision": 1}).status_code == 404
    client.as_user("alice-id")
    assert client.get(url).status_code == 200


def test_stale_edit_or_delete_cannot_lose_items(client):
    p = client.post("/api/mixed-playlists", json=body()).json()
    url = f'/api/mixed-playlists/{p["id"]}'
    assert client.put(url, json=body(1)).status_code == 200
    assert client.put(url, json=body(1)).status_code == 409
    assert client.delete(url, params={"revision": 1}).status_code == 409
    assert client.get(url).json()["revision"] == 2


def test_concurrent_edits_only_one_wins(client):
    p = store.write_playlist("alice-id", PlaylistWrite(**body()))
    def update(_):
        try:
            store.write_playlist("alice-id", PlaylistWrite(**body(1)), p["id"])
            return 200
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(update, range(2))) == [200, 409]


def test_unknown_urls_and_duplicate_item_ids_rejected(client):
    b = body()
    b["items"][0]["track"]["url"] = "http://internal/secret"
    assert client.post("/api/mixed-playlists", json=b).status_code == 422
    b = body()
    b["items"][1]["id"] = b["items"][0]["id"]
    assert client.post("/api/mixed-playlists", json=b).status_code == 422


def test_export_local_subset_creates_new_playlist(client, monkeypatch):
    calls = []
    async def create(name, ids, user, salt, token):
        calls.append((name, ids, user))
        return "created"
    monkeypatch.setattr(mixed_playlists.navidrome_client, "create_playlist", create)
    p = client.post("/api/mixed-playlists", json=body()).json()
    r = client.post(f'/api/mixed-playlists/{p["id"]}/export-navidrome', json={"revision": 1})
    assert r.json() == {"playlistId": "created", "exported": 1, "omitted": 1}
    assert calls == [("My mixed playlist (local copy)", ["local"], "alice-id")]
    assert client.get(f'/api/mixed-playlists/{p["id"]}').json() == p


def test_database_backup_restores_all_playlist_entries(client, tmp_path):
    p = client.post("/api/mixed-playlists", json=body()).json()
    backup = tmp_path / "backup.db"
    with store.connection() as source, sqlite3.connect(backup) as dest:
        source.backup(dest)
    with sqlite3.connect(backup) as c:
        assert json.loads(c.execute("SELECT items FROM playlists").fetchone()[0]) == p["items"]


@pytest.mark.parametrize("suffix", ["Live", "Remix", "Cover", "Instrumental", "Karaoke", "Acoustic", "Remastered", "Taylor's Version"])
def test_version_mismatches_never_auto_match(suffix):
    assert matcher.rank(track(), [track(title="Song " + suffix)])["selected"] is None


def test_exact_match_needs_duration_and_margin():
    expected = track()
    assert matcher.rank(expected, [expected])["selected"] is not None
    assert matcher.rank(track(duration=None), [expected])["selected"] is None
    assert matcher.rank(expected, [expected, expected.model_copy(update={"source_id": "two"})])["selected"] is None
    assert matcher.rank(expected, [track(artist="Another artist")])["selected"] is None
    assert matcher.rank(expected, [track(duration=350)])["selected"] is None


def test_conflicting_recording_ids_block_same_title():
    assert matcher.rank(track(recording_mbid=uuid4()), [track(recording_mbid=uuid4())])["selected"] is None


def test_authorization_is_enforced_server_side(tmp_path, monkeypatch):
    file = tmp_path / "sources.json"
    file.write_text(json.dumps({"authorized_http:one": {"authorization": "own fixture", "stream": True,
        "persist": False, "url": "https://fixture.test/audio.mp3", "metadata": {"title": "Song", "artist": "Artist"}}}))
    monkeypatch.setenv("MUSIC_SOURCES_FILE", str(file))
    assert sources.audio_url("one") == "https://fixture.test/audio.mp3"
    with pytest.raises(HTTPException):
        sources.audio_url("one", "persist")
    with pytest.raises(HTTPException):
        sources.audio_url("unknown")
    assert sources.public_tracks("Song")[0].source_id == "one"


@pytest.mark.parametrize("url", ["http://r.googlevideo.com/x", "https://evil.test/x", "https://r.googlevideo.com.evil/x", "https://r.googlevideo.com:8000/x", "https://u:p@r.googlevideo.com/x"])
def test_extracted_stream_origin_rejected(url):
    with pytest.raises(HTTPException):
        _safe_stream(url, {})


def test_media_headers_never_forward_secrets():
    _, headers = _safe_stream("https://r.googlevideo.com/audio", {"Cookie": "secret", "Authorization": "secret", "User-Agent": "test"})
    assert headers == {"User-Agent": "test"}
