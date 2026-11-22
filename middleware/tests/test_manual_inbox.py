"""Private inbox/upload regression tests. Services are simulated; media is synthetic."""
import asyncio
import errno
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

import db
from auth import get_current_session
from homelab import manual_inbox as inbox
from homelab import operations, store
from routes import manual_inbox as routes
from services import safe_files


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "armonia.db")
    db.init_db()
    store.init()
    music = tmp_path / "music"
    music.mkdir()
    monkeypatch.setattr(safe_files, "MUSIC_DIR", str(music))
    monkeypatch.setenv("MUSIC_FREE_SPACE_RESERVE_BYTES", "0")
    sessions = {}
    for user in ("alice", "bob"):
        root = music / user
        root.mkdir()
        sid = db.create_session(user, "s", "fixture-token", str(root), library_id=7, user_id=user)
        sessions[user] = db.get_session(sid)
    sess = sessions["alice"]
    job = SimpleNamespace(username="nd:alice", import_id="import-id", name="Fixture list",
                          items=[{"track": {"title": "Tone", "artist": "Fixture", "album": "Lab", "duration": 10}}])
    with db._conn() as connection:
        inbox.enqueue_omitted(connection, job, 0)
    item = inbox.list_items(sess)[0]
    calls = {"converted": 0, "scan": 0, "permissions": 0, "songs": [], "indexed": ["new-song"]}

    async def grant(session):
        db.require_active_session(session)
        calls["permissions"] += 1
        return 7

    async def convert(original, output):
        calls["converted"] += 1
        output.write_bytes(original.read_bytes())

    async def songs(*args, **kwargs):
        return [entry if isinstance(entry, dict) else {"id": entry, "title": "Tone", "artist": "Fixture"}
                for entry in calls["songs"]]

    async def scan(*args, done, **kwargs):
        calls["scan"] += 1
        marker = inbox.owned(item["id"], sess).get("uploadMarker")
        calls["songs"] += [{"id": ident, "title": "Tone", "artist": "Fixture", "comment": marker}
                           for ident in calls["indexed"]]
        return await done()

    monkeypatch.setattr(routes.nd, "require_library_access", grant)
    monkeypatch.setattr(routes.nd, "_search_songs_strict", songs)
    monkeypatch.setattr(routes.nd, "scan_until", scan)
    monkeypatch.setattr(routes, "_convert", convert)
    monkeypatch.setattr(routes, "_tag_upload", lambda *args: None)
    monkeypatch.setattr(routes.tagger_service, "tag", lambda *args: None)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_session] = lambda: sess
    return SimpleNamespace(sess=sess, bob=sessions["bob"], item=item, job=job, calls=calls,
                           root=music / "alice", app=app, client=TestClient(app))


def post_file(lab, **kwargs):
    return lab.client.post(f"/api/manual-inbox/{lab.item['id']}/upload", content=b"synthetic audio",
                           headers={"Content-Type": "audio/mpeg", "X-Item-Revision": str(lab.item["revision"])},
                           **kwargs)


def test_explicit_enqueue_is_atomic_idempotent_and_independent_of_import_history(lab):
    with db._conn() as connection:
        inbox.enqueue_omitted(connection, lab.job, 0)
        connection.execute("DELETE FROM playlist_imports")
    assert len(inbox.list_items(lab.sess)) == 1
    assert inbox.list_items(lab.bob) == []
    with pytest.raises(RuntimeError), db._conn() as connection:
        lab.job.import_id = "rolled-back"
        inbox.enqueue_omitted(connection, lab.job, 0)
        raise RuntimeError("checkpoint failed")
    assert len(inbox.list_items(lab.sess)) == 1
    db.init_db()
    assert inbox.list_items(lab.sess)[0]["originName"] == "Fixture list"


def test_other_user_cannot_list_upload_refresh_or_delete(lab):
    lab.app.dependency_overrides[get_current_session] = lambda: lab.bob
    assert lab.client.get("/api/manual-inbox").json() == {"items": []}
    assert post_file(lab).status_code == 404
    path = f"/api/manual-inbox/{lab.item['id']}"
    assert lab.client.post(path + "/refresh", json={"revision": 0}).status_code == 404
    assert lab.client.request("DELETE", path, json={"revision": 0}).status_code == 404
    assert not lab.calls["converted"]


def test_raw_upload_publishes_only_in_owner_library_and_never_creates_playlist(lab):
    result = post_file(lab)
    assert result.status_code == 200, result.text
    item = result.json()
    assert item["status"] == "saved" and item["songId"] == "new-song" and item["error"] is None
    assert "uploadMarker" not in item and "libraryRoot" not in item
    files = list(lab.root.rglob("*.mp3"))
    assert len(files) == 1 and files[0].read_bytes() == b"synthetic audio"
    assert not list(lab.root.parent.joinpath("bob").rglob("*.mp3"))
    assert store.playlists("alice") == []
    assert lab.calls["permissions"] == 2
    # Removing the reminder must never remove a saved track.
    response = lab.client.request("DELETE", f"/api/manual-inbox/{item['id']}", json={"revision": item["revision"]})
    assert response.status_code == 200 and files[0].exists()
    assert lab.client.get("/api/manual-inbox").json() == {"items": []}


def test_duplicate_upload_and_refresh_do_not_write_twice(lab):
    lab.calls["indexed"] = []
    saved = post_file(lab).json()
    assert saved["status"] == "saved" and saved["error"] == "index_pending" and saved["songId"] is None
    assert post_file(lab).status_code == 409  # stale revision
    lab.item = saved
    again = post_file(lab)
    assert again.status_code == 200 and lab.calls["converted"] == 1
    lab.calls["indexed"] = ["new-song"]
    refreshed = lab.client.post(f"/api/manual-inbox/{saved['id']}/refresh", json={"revision": again.json()["revision"]})
    assert refreshed.status_code == 200 and refreshed.json()["songId"] == "new-song"
    assert len(list(lab.root.rglob("*.mp3"))) == 1 and lab.calls["converted"] == 1


def test_previous_identical_metadata_does_not_claim_existing_song(lab):
    lab.calls["songs"] = ["old-song"]
    lab.calls["indexed"] = []
    result = post_file(lab).json()
    assert result["status"] == "saved" and result["songId"] is None and result["error"] == "index_pending"


def test_ambiguous_new_index_ids_remain_pending(lab):
    lab.calls["indexed"] = ["new-one", "new-two"]
    result = post_file(lab).json()
    assert result["songId"] is None and result["error"] == "index_pending"


def test_concurrent_identical_metadata_with_other_marker_cannot_claim_our_file(lab):
    lab.calls["songs"] = [{"id": "concurrent-other", "title": "Tone", "artist": "Fixture",
                            "comment": "armonia-manual:other-upload"}]
    lab.calls["indexed"] = []
    result = post_file(lab).json()
    assert result["status"] == "saved" and result["songId"] is None and result["error"] == "index_pending"


def test_exact_file_marker_wins_over_concurrent_metadata_match(lab):
    lab.calls["songs"] = [{"id": "concurrent-other", "title": "Tone", "artist": "Fixture",
                            "comment": "armonia-manual:other-upload"}]
    result = post_file(lab).json()
    assert result["songId"] == "new-song" and result["error"] is None


def test_receipt_recovers_crash_after_publication_without_duplicate(lab, monkeypatch):
    original = inbox.update

    def fail(item, sess, **changes):
        if changes.get("status") == "saved":
            raise HTTPException(503, "simulated checkpoint failure")
        return original(item, sess, **changes)

    monkeypatch.setattr(inbox, "update", fail)
    assert post_file(lab).status_code == 503
    assert len(list(lab.root.rglob("*.mp3"))) == 1
    marker = inbox.owned(lab.item["id"], lab.sess)["uploadMarker"]
    assert marker.startswith("armonia-manual:")
    monkeypatch.setattr(inbox, "update", original)
    lab.item = lab.client.get("/api/manual-inbox").json()["items"][0]
    assert lab.item["status"] == "pending"
    restored = post_file(lab)
    assert restored.status_code == 200 and restored.json()["status"] == "saved"
    assert restored.json()["songId"] == "new-song"
    assert inbox.owned(lab.item["id"], lab.sess)["uploadMarker"] == marker
    assert lab.calls["converted"] == 1 and len(list(lab.root.rglob("*.mp3"))) == 1


def test_revoked_session_or_library_grant_cannot_publish(lab, monkeypatch):
    async def revoked(session):
        lab.calls["permissions"] += 1
        if lab.calls["permissions"] > 1:
            raise HTTPException(403, "library permission revoked")
        return 7

    monkeypatch.setattr(routes.nd, "require_library_access", revoked)
    assert post_file(lab).status_code == 403
    assert not list(lab.root.rglob("*.mp3"))
    db.delete_session(lab.sess["id"])
    assert post_file(lab).status_code == 401
    assert lab.client.get("/api/manual-inbox").status_code == 401


def test_logout_during_copy_blocks_atomic_publication(lab, monkeypatch):
    original = safe_files.shutil.copyfileobj

    def revoke(src, target):
        original(src, target)
        db.delete_session(lab.sess["id"])

    monkeypatch.setattr(safe_files.shutil, "copyfileobj", revoke)
    assert post_file(lab).status_code == 401
    assert not [file for file in lab.root.rglob("*") if file.is_file()]


def test_unavailable_index_search_retains_exact_published_file_for_refresh(lab, monkeypatch):
    async def unavailable(*args, **kwargs):
        raise HTTPException(503, "service unavailable")

    monkeypatch.setattr(routes.nd, "_search_songs_strict", unavailable)
    result = post_file(lab)
    assert result.status_code == 200 and result.json()["error"] == "index_pending"
    assert len(list(lab.root.rglob("*.mp3"))) == 1


def test_index_failure_preserves_audio_and_can_refresh(lab, monkeypatch):
    async def unavailable(*args, **kwargs):
        raise RuntimeError("simulated index outage")

    monkeypatch.setattr(routes.nd, "scan_until", unavailable)
    result = post_file(lab)
    assert result.status_code == 200 and result.json()["error"] == "index_pending"
    assert result.json()["status"] == "saved" and len(list(lab.root.rglob("*.mp3"))) == 1


def test_same_item_reservation_blocks_upload_delete_and_refresh(lab):
    path = f"/api/manual-inbox/{lab.item['id']}"
    with operations.reserve("nd:alice", "manual:" + lab.item["id"]):
        assert post_file(lab).status_code == 409
        assert lab.client.request("DELETE", path, json={"revision": 0}).status_code == 409
        assert lab.client.post(path + "/refresh", json={"revision": 0}).status_code == 409
    assert post_file(lab).status_code == 200


def test_saturated_upload_slots_fail_in_bounded_time(lab, monkeypatch):
    async def check():
        monkeypatch.setattr(routes, "_slots", asyncio.Semaphore(0))
        with pytest.raises(HTTPException) as error:
            async with routes._upload_slot():
                pytest.fail("saturated slot was granted")
        assert error.value.status_code == 429
    asyncio.run(asyncio.wait_for(check(), timeout=2))


def test_library_reassignment_during_upload_cannot_publish(lab, monkeypatch):
    async def reassigned(session):
        lab.calls["permissions"] += 1
        return 7 if lab.calls["permissions"] == 1 else 8
    monkeypatch.setattr(routes.nd, "require_library_access", reassigned)
    assert post_file(lab).status_code == 409
    assert not list(lab.root.rglob("*.mp3"))


@pytest.mark.parametrize("body,ctype,expected", [(b"", "audio/mpeg", 422), (b"test", "text/plain", 415),
                                                (b"oversized", "audio/mpeg", 413)])
def test_invalid_uploads_fail_without_publication(lab, monkeypatch, body, ctype, expected):
    monkeypatch.setattr(routes, "MAX_UPLOAD", 5)
    response = lab.client.post(f"/api/manual-inbox/{lab.item['id']}/upload", content=body,
                               headers={"Content-Type": ctype, "X-Item-Revision": "0"})
    assert response.status_code == expected and not lab.calls["converted"]
    assert not list(lab.root.rglob("*.mp3"))


def test_stream_limit_is_enforced_without_content_length(lab, tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "MAX_UPLOAD", 4)

    async def chunks():
        yield b"123"
        yield b"456"

    request = SimpleNamespace(headers={}, stream=chunks)
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes._receive(request, tmp_path / "stage", lab.sess))
    assert error.value.status_code == 413


def test_interrupted_upload_has_clear_error_and_no_publication(lab, tmp_path):
    async def interrupted():
        yield b"fragment"
        raise ClientDisconnect()
    request = SimpleNamespace(headers={}, stream=interrupted)
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes._receive(request, tmp_path / "interrupted", lab.sess))
    assert error.value.status_code == 400
    assert not list(lab.root.rglob("*.mp3"))


def test_logout_mid_upload_is_checked_on_each_chunk(lab, tmp_path):
    async def revoked():
        yield b"before"
        db.delete_session(lab.sess["id"])
        yield b"after"
    request = SimpleNamespace(headers={}, stream=revoked)
    output = tmp_path / "revoked"
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes._receive(request, output, lab.sess))
    assert error.value.status_code == 401 and output.read_bytes() == b"before"


def test_failed_receipt_prevents_publication_and_cleans_partial_file(lab, monkeypatch):
    def failed(*args):
        raise HTTPException(503, "journal busy")
    monkeypatch.setattr(routes.publications, "record", failed)
    assert post_file(lab).status_code == 503
    assert not [path for path in lab.root.rglob("*") if path.is_file()]


def test_disk_reserve_and_disk_full_have_safe_errors(lab, monkeypatch):
    monkeypatch.setattr(routes.shutil, "disk_usage", lambda root: SimpleNamespace(free=0))
    assert post_file(lab).status_code == 507
    assert not list(lab.root.rglob("*.mp3"))

    async def full(*args):
        raise OSError(errno.ENOSPC, "fixture full")

    monkeypatch.setattr(routes, "_convert", full)
    assert post_file(lab).status_code == 507


def test_symlinked_library_and_changed_library_reject_upload(lab):
    real = lab.root.with_name("real")
    lab.root.rename(real)
    lab.root.symlink_to(real, target_is_directory=True)
    assert post_file(lab).status_code == 403
    lab.root.unlink()
    real.rename(lab.root)
    item = inbox.owned(lab.item["id"], lab.sess)
    lab.item = inbox.update(item, lab.sess, libraryRoot="/old-library")
    assert post_file(lab).status_code == 409


def test_missing_previously_saved_audio_does_not_silently_recreate(lab):
    lab.item = post_file(lab).json()
    for file in lab.root.rglob("*.mp3"):
        file.unlink()
    assert post_file(lab).status_code == 409
    assert lab.calls["converted"] == 1


def test_stale_delete_cannot_lose_new_state(lab):
    inbox.update(inbox.owned(lab.item["id"], lab.sess), lab.sess, error="index_pending")
    result = lab.client.request("DELETE", f"/api/manual-inbox/{lab.item['id']}", json={"revision": 0})
    assert result.status_code == 409 and len(inbox.list_items(lab.sess)) == 1


REAL_CONVERT = routes._convert
REAL_TAG = routes.tagger_service.tag
REAL_TAG_UPLOAD = routes._tag_upload


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg unavailable")
def test_real_decoder_accepts_only_synthetic_mp3_and_strips_source_tags(tmp_path):
    original, converted = tmp_path / "fixture.mp3", tmp_path / "clean.mp3"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
                    "-metadata", "title=untrusted source title", "-c:a", "libmp3lame", str(original)], check=True)
    asyncio.run(REAL_CONVERT(original, converted))
    from mutagen import File
    assert File(converted, easy=True).info.length > 0
    assert "title" not in File(converted, easy=True)
    original.write_bytes(b"#EXTM3U\nhttps://fixture.invalid/not-allowed.mp3\n")
    with pytest.raises(HTTPException) as error:
        asyncio.run(REAL_CONVERT(original, tmp_path / "invalid.mp3"))
    assert error.value.status_code == 422


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg unavailable")
def test_real_mp3_endpoint_decodes_retags_and_atomically_publishes(lab, tmp_path, monkeypatch):
    from mutagen import File
    original = tmp_path / "synthetic.mp3"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
                    "-metadata", "title=wrong original", "-c:a", "libmp3lame", str(original)], check=True)
    monkeypatch.setattr(routes, "_convert", REAL_CONVERT)
    monkeypatch.setattr(routes.tagger_service, "tag", REAL_TAG)
    monkeypatch.setattr(routes, "_tag_upload", REAL_TAG_UPLOAD)
    response = lab.client.post(f"/api/manual-inbox/{lab.item['id']}/upload", content=original.read_bytes(),
                               headers={"Content-Type": "audio/mpeg", "X-Item-Revision": "0",
                                        "Content-Disposition": 'attachment; filename="../../outside.mp3"'})
    assert response.status_code == 200, response.text
    saved = list(lab.root.rglob("*.mp3"))
    assert len(saved) == 1 and File(saved[0], easy=True).info.length > 0
    audio = File(saved[0], easy=True)
    assert audio["title"] == ["Tone"] and audio["artist"] == ["Fixture"] and audio["album"] == ["Lab"]
    from mutagen.id3 import ID3
    marker = inbox.owned(lab.item["id"], lab.sess)["uploadMarker"]
    assert str(ID3(saved[0]).getall("COMM")[0]) == marker
    assert not (tmp_path / "outside.mp3").exists()
