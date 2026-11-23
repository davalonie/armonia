"""A login-time library grant must not authorize future filesystem writes."""
import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import db
from auth import get_current_session
from homelab import store
from routes import download, import_playlist, sources, tracks
from services import navidrome_client as nd
from services import safe_files
from services import ytdlp_service as yt

SESSION = {"user_id": "alice-id", "username": "alice", "salt": "s", "token": "t",
           "library_path": "/music/alice", "library_id": 7, "is_admin": True}


@pytest.fixture(autouse=True)
def live_session(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "session.db")
    db.init_db()
    store.init()
    sid = db.create_session("alice", "s", "t", "/music/alice", library_id=7, user_id="alice-id")
    monkeypatch.setitem(SESSION, "id", sid)


def mock_folders(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(nd.httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw))


def folders(*ids):
    return httpx.Response(200, json={"subsonic-response": {"status": "ok",
        "musicFolders": {"musicFolder": [{"id": i, "name": "Private"} for i in ids]}}})


def test_current_grant_not_cached_and_other_library_does_not_authorize(monkeypatch):
    available = [7]
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.path == "/rest/getMusicFolders"
        assert request.url.params["u"] == "alice" and request.url.params["t"] == "t"
        return folders(*available)
    mock_folders(monkeypatch, handler)
    assert asyncio.run(nd.require_library_access(SESSION)) == 7
    available[:] = [8]
    with pytest.raises(HTTPException) as error:
        asyncio.run(nd.require_library_access(SESSION))
    assert error.value.status_code == 403 and len(requests) == 2
    available[:] = [7, 8]
    assert asyncio.run(nd.require_library_access(SESSION)) == 7


@pytest.mark.parametrize("response,expected", [
    (httpx.Response(200, json={"subsonic-response": {"status": "failed", "error": {"code": 40}}}), 403),
    (folders(), 403),
    (httpx.Response(503), 503),
    (httpx.Response(200, content=b"invalid json"), 503),
    (httpx.Response(200, json={}), 503),
    (httpx.Response(302, headers={"Location": "https://unexpected/"}), 503),
])
def test_auth_failure_empty_grant_unavailable_and_malformed_fail_closed(monkeypatch, response, expected):
    mock_folders(monkeypatch, lambda request: response)
    with pytest.raises(HTTPException) as error:
        asyncio.run(nd.require_library_access(SESSION))
    assert error.value.status_code == expected


def test_old_session_without_library_id_cannot_guess_write_authority():
    with pytest.raises(HTTPException) as error:
        asyncio.run(nd.require_library_access({**SESSION, "library_id": None}))
    assert error.value.status_code == 403


@pytest.mark.parametrize("path,body", [
    ("/api/download", {"videoId": "abcdefghijk", "artist": "Fixture", "title": "Tone"}),
    ("/api/downloads/old/retry", None),
    ("/api/import/spotify", {"url": "https://open.spotify.com/playlist/fixture"}),
    ("/api/sources/fixture/save", None),
])
def test_all_write_entrypoints_recheck_before_scheduling_or_fetching(monkeypatch, path, body):
    mock_folders(monkeypatch, lambda request: folders(8))
    monkeypatch.setattr(sources.sources, "allowed", lambda *args: {"persist": True})
    app = FastAPI()
    for module in (download, import_playlist, sources):
        app.include_router(module.router)
    app.dependency_overrides[get_current_session] = lambda: SESSION
    assert TestClient(app).post(path, json=body).status_code == 403


@pytest.mark.parametrize("revoked", [False, True])
def test_queued_download_rechecks_in_worker_before_publish(monkeypatch, tmp_path, revoked):
    root = tmp_path / "music"
    root.mkdir()
    monkeypatch.setattr(yt, "MUSIC_DIR", str(root))
    monkeypatch.setenv("MUSIC_FREE_SPACE_RESERVE_BYTES", "0")
    monkeypatch.setattr(yt.tagger_service, "tag", lambda *args: None)
    def stage(video_id, artist, title, source, cancel, directory):
        path = Path(directory) / "fixture.mp3"
        path.write_bytes(b"authorized fixture audio")
        return str(path), {}
    monkeypatch.setattr(yt, "_download_staged", stage)
    calls = []
    async def authorize():
        calls.append(True)
        if revoked and len(calls) == 2:
            raise HTTPException(403, "revoked during download")
    async def run():
        return await yt.download_limited("abcdefghijk", "Fixture", "Tone", music_dir=str(root), authorize=authorize)
    if revoked:
        with pytest.raises(HTTPException):
            asyncio.run(run())
        assert not list(root.iterdir())
    else:
        result = asyncio.run(run())
        assert Path(result).read_bytes() == b"authorized fixture audio"
    assert len(calls) == 2


def test_http_import_rechecks_after_conversion_without_publishing(monkeypatch, tmp_path):
    from mutagen.id3 import ID3
    root = tmp_path / "music"
    root.mkdir()
    monkeypatch.setattr(safe_files, "MUSIC_DIR", str(root))
    monkeypatch.setenv("MUSIC_FREE_SPACE_RESERVE_BYTES", "0")
    available = [7]
    mock_folders(monkeypatch, lambda request: folders(*available))
    record = {"metadata": {"artist": "Fixture", "title": "Tone"}}
    monkeypatch.setattr(sources.sources, "allowed", lambda *args: record)
    monkeypatch.setattr(sources.sources, "audio_url", lambda *args: "https://fixture/audio")
    async def fetch(*args):
        return b"fixture", "audio/mpeg"
    async def known(*args):
        return set()
    class Process:
        async def wait(self):
            return 0
    async def convert(*args, **kw):
        ID3().save(args[-1])
        # The same account loses access during the network/conversion work.
        available[:] = [8]
        return Process()
    monkeypatch.setattr(sources.audio_cache, "fetch", fetch)
    monkeypatch.setattr(nd, "matching_song_ids", known)
    monkeypatch.setattr(sources.asyncio, "create_subprocess_exec", convert)
    monkeypatch.setattr(sources.tagger_service, "tag", lambda *args: None)
    app = FastAPI()
    app.include_router(sources.router)
    app.dependency_overrides[get_current_session] = lambda: {**SESSION, "library_path": str(root)}
    assert TestClient(app).post("/api/sources/fixture/save").status_code == 403
    assert not list(root.iterdir())


def test_old_admin_role_does_not_authorize_deletion(monkeypatch):
    monkeypatch.setattr(tracks, "DELETE_USERS", {"alice"})
    async def demoted(*args):
        return False
    monkeypatch.setattr(nd, "is_admin", demoted)
    app = FastAPI()
    app.include_router(tracks.router)
    app.dependency_overrides[get_current_session] = lambda: SESSION
    assert TestClient(app).delete("/api/track/anything").status_code == 403
