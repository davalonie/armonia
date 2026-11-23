import logging
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import db
from auth import COOKIE_NAME
from routes import auth, import_playlist, tracks
from services import safe_files, ytdlp_service
from services.safe_logging import RedactSecrets


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app.db")
    db.init_db()
    auth._login_failures.clear()
    async def ping(*args):
        return {"status": "ok"}
    async def libs(username, password):
        return {"id": "fictional-user-id-" + username, "libraries": []}
    async def admin(*args):
        return False
    monkeypatch.setattr(auth, "ping", ping)
    monkeypatch.setattr(auth, "get_user_context", libs)
    monkeypatch.setattr(auth, "get_is_admin", admin)
    app = FastAPI()
    for r in (auth.router, import_playlist.router, tracks.router):
        app.include_router(r)
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    import_playlist._imports.clear()


def login(c, user="alice", web=False):
    return c.post("/api/login", json={"username": user, "password": "fictional"},
                  headers={"X-Music-Client": "web"} if web else {})


def test_cookie_login_hides_bearer_and_protects_mutations(client):
    result = login(client, web=True)
    assert result.status_code == 200
    assert result.json() == {"username": "alice", "userId": "fictional-user-id-alice"}
    cookie = result.headers["set-cookie"]
    assert all(flag in cookie for flag in ("HttpOnly", "Secure", "SameSite=strict"))
    assert client.get("/api/me").status_code == 403
    assert client.get("/api/me", headers={"X-Music-Client": "web"}).status_code == 200
    assert client.post("/api/logout").status_code == 403
    assert client.post("/api/logout", headers={"X-Music-Client": "web", "Origin": "https://evil.test"}).status_code == 403
    old = client.cookies.get(COOKIE_NAME)
    assert client.post("/api/logout", headers={"X-Music-Client": "web"}).status_code == 200
    assert db.get_session(old) is None


def test_native_header_works_but_query_bearer_does_not(client):
    sid = login(client).json()["sessionId"]
    assert client.get("/api/me", params={"session": sid}).status_code == 401
    assert client.get("/api/me", headers={"X-Session-Id": sid}).status_code == 200
    assert client.get("/api/preview/not-valid", params={"session": sid}).status_code == 401


def test_stale_client_identity_cannot_use_a_different_accounts_cookie(client):
    login(client, "bob", web=True)
    assert client.get("/api/me", headers={"X-Music-Client": "web", "X-Music-Owner": "fictional-user-id-alice"}).status_code == 409


def test_tls_proxy_origin_must_match_configured_origin(client, monkeypatch):
    login(client, web=True)
    monkeypatch.setenv("MUSIC_PUBLIC_ORIGIN", "https://music.private.example")
    assert client.get("/api/me", headers={"X-Music-Client": "web", "Origin": "https://evil.test"}).status_code == 403
    assert client.get("/api/me", headers={"X-Music-Client": "web", "Origin": "https://music.private.example"}).status_code == 200


def test_tokens_encrypted_and_session_ids_hashed(client):
    sid = login(client).json()["sessionId"]
    session = db.get_session(sid)
    with sqlite3.connect(db.DB_PATH) as c:
        stored_id, stored_token = c.execute("SELECT id, token FROM sessions").fetchone()
    assert stored_id == db.session_key(sid) and stored_id != sid
    assert stored_token != session["token"]
    assert session["token"].encode() not in db.DB_PATH.read_bytes()
    assert os.stat(db.DB_PATH.parent / "credential.key").st_mode & 0o777 == 0o600
    db.init_db()
    assert db.get_session(sid) is not None  # non-destructive subsequent migrations


def test_forwarded_header_does_not_bypass_limit(client, monkeypatch):
    async def rejected(*args):
        return {"status": "failed"}
    monkeypatch.setattr(auth, "ping", rejected)
    for n in range(8):
        assert client.post("/api/login", json={"username": "u", "password": "bad"},
                           headers={"X-Forwarded-For": f"192.0.2.{n}"}).status_code == 401
    assert client.post("/api/login", json={"username": "u", "password": "bad"},
                       headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 429


def test_import_is_private_even_when_id_known(client):
    import_playlist._imports["known"] = import_playlist.ImportJob("known", "private songs", 1, username="nd:fictional-user-id-alice")
    alice = login(client).json()["sessionId"]
    bob = login(client, "bob").json()["sessionId"]
    assert client.get("/api/import/known", headers={"X-Session-Id": alice}).status_code == 200
    response = client.get("/api/import/known", headers={"X-Session-Id": bob})
    assert response.status_code == 404 and "private songs" not in response.text


def test_deletion_requires_explicit_grant_before_any_upstream_call(client):
    sid = login(client).json()["sessionId"]
    assert client.delete("/api/track/shared", headers={"X-Session-Id": sid}).status_code == 403


@pytest.mark.parametrize("path", ["../private.mp3", "/elsewhere/file.mp3", "a/../../file.mp3", ""])
def test_reject_paths_outside_root(tmp_path, path):
    with pytest.raises(ValueError):
        safe_files.relative_file(tmp_path, path)


def test_library_never_falls_back_to_global(tmp_path):
    with pytest.raises(ValueError):
        safe_files.library_root("/other/library", str(tmp_path))


def test_directory_symlink_blocks_delete_and_publish(tmp_path):
    root = tmp_path / "music"
    outside = tmp_path / "documents"
    root.mkdir()
    outside.mkdir()
    sensitive = outside / "song.mp3"
    sensitive.write_bytes(b"keep")
    (root / "Artist").symlink_to(outside, target_is_directory=True)
    staged = tmp_path / "staged.mp3"
    staged.write_bytes(b"new")
    with pytest.raises(OSError):
        safe_files.unlink_music(root, "Artist/song.mp3")
    with pytest.raises(OSError):
        safe_files.publish(staged, root, "Artist", "Song")
    assert sensitive.read_bytes() == b"keep"
    assert list(outside.iterdir()) == [sensitive]


def test_final_links_rejected(tmp_path):
    other = tmp_path / "other.mp3"
    other.write_bytes(b"keep")
    (tmp_path / "link.mp3").symlink_to(other)
    with pytest.raises(ValueError):
        safe_files.unlink_music(tmp_path, "link.mp3")
    os.link(other, tmp_path / "hard.mp3")
    with pytest.raises(ValueError):
        safe_files.unlink_music(tmp_path, "hard.mp3")
    assert other.read_bytes() == b"keep"


def test_parent_swap_cannot_redirect_unlink(tmp_path, monkeypatch):
    artist = tmp_path / "music" / "Artist"
    artist.mkdir(parents=True)
    (artist / "song.mp3").write_bytes(b"music")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "song.mp3").write_bytes(b"private")
    real = os.unlink
    def swap(name, *, dir_fd):
        artist.rename(artist.with_name("old"))
        artist.symlink_to(outside, target_is_directory=True)
        real(name, dir_fd=dir_fd)
    monkeypatch.setattr(os, "unlink", swap)
    safe_files.unlink_music(tmp_path / "music", "Artist/song.mp3")
    assert (outside / "song.mp3").read_bytes() == b"private"


def test_publishing_never_overwrites_existing_music(tmp_path):
    staged = tmp_path / "staged.mp3"
    staged.write_bytes(b"audio")
    a = safe_files.publish(staged, tmp_path, "Artist", "Title")
    b = safe_files.publish(staged, tmp_path, "Artist", "Title")
    assert a != b and Path(a).read_bytes() == Path(b).read_bytes() == b"audio"


def test_download_tags_only_private_staging(tmp_path, monkeypatch):
    music = tmp_path / "music"
    music.mkdir()
    monkeypatch.setattr(ytdlp_service, "MUSIC_DIR", str(music))
    def fake(video, artist, title, source, cancel, staging):
        path = Path(staging) / "test.mp3"
        path.write_bytes(b"audio")
        return str(path), {}
    def tag(path, *args):
        assert not Path(path).is_relative_to(music)
        Path(path).write_bytes(b"tagged")
    monkeypatch.setattr(ytdlp_service, "_download_staged", fake)
    monkeypatch.setattr(ytdlp_service.tagger_service, "tag", tag)
    result = ytdlp_service.download("fictional01", "Artist", "Song")
    assert Path(result).read_bytes() == b"tagged"


def test_access_log_drops_all_query_parameters():
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 1, '%s - "%s %s HTTP/%s" %d',
                            ("127.0.0.1", "GET", "/api/stream/1?session=secret", "1.1", 401), None)
    RedactSecrets().filter(rec)
    assert "secret" not in rec.getMessage() and "session" not in rec.getMessage()


def test_http_error_log_redacts_navidrome_credentials():
    rec = logging.LogRecord("httpx", logging.INFO, "", 1, 'request %s',
                            ("http://nav/rest/ping?u=u&t=secret&s=salt",), None)
    RedactSecrets().filter(rec)
    assert "secret" not in rec.getMessage() and "salt" not in rec.getMessage()
