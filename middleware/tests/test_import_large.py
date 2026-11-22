"""Large imports: bounded progress writes, playlist creation in a form body, queue control."""
import asyncio
import json

import httpx
import pytest

import db
from routes import import_batch as batch
from routes import import_playlist as imp
from services import navidrome_client as nd


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "armonia.db")
    db.init_db()
    monkeypatch.setattr(imp, "_imports", {})
    monkeypatch.setattr(imp, "_written", {})
    monkeypatch.setattr(imp, "_dirty", set())
    writes = []
    original = imp._write_locked

    def counted(job, *args):
        writes.append(job.revision)
        return original(job, *args)

    monkeypatch.setattr(imp, "_write_locked", counted)
    return writes


def stored(job):
    with db._conn() as c:
        return json.loads(c.execute("SELECT payload FROM playlist_imports WHERE id=?", (job.import_id,)).fetchone()[0])


def job_of(n):
    job = imp.ImportJob("large", "Grande", n, username="nd:alice-id", durable=True)
    job.items = [imp.new_item({"title": f"T{i}", "artist": "A", "album": "", "duration": 200}) for i in range(n)]
    job.status = "running"
    return job


def test_progress_of_a_running_import_is_coalesced_and_always_reaches_the_database(store):
    writes = store
    job = job_of(30)

    async def scenario():
        imp.save(job)                               # stage boundary: written at once
        for item in job.items:
            item["state"] = "ready"
            imp.save(job, progress=True)            # one per song: coalesced
        assert len(writes) == 1 and imp._dirty == {job.import_id}
        await asyncio.sleep(imp.PROGRESS_INTERVAL + 0.2)
        assert len(writes) == 2 and stored(job)["revision"] == job.revision
        assert stored(job)["current"] == 30

    asyncio.run(scenario())


def test_choices_and_the_end_of_an_import_are_never_deferred(store):
    writes = store
    job = job_of(3)

    async def scenario():
        imp.save(job)
        job.items[0]["state"] = "ready"
        imp.save(job, progress=True)
        assert len(writes) == 1
        job.items[1].update(state="pending", decision="confirmed")
        imp.save(job)                               # a choice: written now, with the pending progress
        assert len(writes) == 2 and not imp._dirty
        assert stored(job)["items"][0]["state"] == "ready"
        job.status = "done"
        imp.save(job, progress=True)                # not running any more: written now
        assert len(writes) == 3 and stored(job)["status"] == "done"

    asyncio.run(scenario())


def test_payload_is_the_same_json_as_before_without_the_worker_gate(store):
    import dataclasses
    job = job_of(2)
    imp.save(job)
    expected = dataclasses.asdict(job)
    expected.pop("review_accepting")
    assert stored(job) == expected


def test_playlist_creation_sends_thousands_of_songs_in_a_form_body(monkeypatch):
    seen = {}

    def answer(request):
        seen.update(method=request.method, url=str(request.url), body=request.content.decode())
        return httpx.Response(200, json={"subsonic-response": {"status": "ok", "playlist": {"id": "p1"}}})

    original = httpx.AsyncClient
    monkeypatch.setattr(nd, "_client", lambda **kw: original(transport=httpx.MockTransport(answer)))
    ids = [f"song{i:05d}" for i in range(2000)]
    assert asyncio.run(nd.create_playlist("Me gusta", ids, "fixture", "salt", "token")) == "p1"
    assert seen["method"] == "POST" and "songId" not in seen["url"] and len(seen["url"]) < 500
    assert seen["body"].count("songId=") == 2000 and "name=Me+gusta" in seen["body"]


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "armonia.db")
    db.init_db()
    sess = db.get_session(db.create_session("alice", "salt", "token", str(tmp_path), library_id=1, user_id="alice-id"))
    monkeypatch.setattr(imp, "_imports", {})
    monkeypatch.setenv("MUSIC_YOUTUBE_CAPABILITIES", "stream,persist")
    monkeypatch.delenv("MUSIC_SOURCES_FILE", raising=False)
    created = []

    async def require(session):
        return 1

    async def find(artist, title, *args):
        return "song-" + title

    async def scan(*args):
        pass

    async def create(name, ids, *args):
        created.append((name, len(ids)))
        return "playlist-" + name

    monkeypatch.setattr(imp.navidrome_client, "require_library_access", require)
    monkeypatch.setattr(imp.navidrome_client, "find_song_id", find)
    monkeypatch.setattr(imp.navidrome_client, "trigger_scan_and_wait", scan)
    monkeypatch.setattr(imp.navidrome_client, "create_playlist", create)
    return sess, created


async def drain():
    while imp._chained:
        await asyncio.gather(*list(imp._chained), return_exceptions=True)


def source(name, n):
    return {"name": name, "tracks": [{"title": f"{name}{i}", "artist": "A", "duration": 200} for i in range(n)]}


def test_a_whole_liked_library_is_one_playlist(lab):
    sess, created = lab
    shown = batch.from_spotify(batch.SourceBatch(playlists=[source("Me gusta", 1830)]), sess)
    assert [(p["total"], p["note"]) for p in shown["playlists"]] == [(1830, None)]

    async def scenario():
        await batch.start(shown["id"], batch.Start(selected=[0]), sess)
        await drain()

    asyncio.run(scenario())
    assert created == [("Me gusta", 1830)]


def test_waiting_playlists_can_be_removed_from_the_queue(lab):
    sess, created = lab
    shown = batch.from_spotify(batch.SourceBatch(playlists=[source("Una", 1), source("Dos", 1), source("Tres", 1)]), sess)
    stored_batch = batch._load(shown["id"], "nd:alice-id")
    stored_batch["status"] = "paused"
    for entry in stored_batch["playlists"]:
        entry["state"] = "waiting"
    batch._save(shown["id"], "nd:alice-id", stored_batch)
    batch.remove(shown["id"], batch.Remove(index=1), sess)
    with pytest.raises(Exception) as again:
        batch.remove(shown["id"], batch.Remove(index=1), sess)
    assert getattr(again.value, "status_code", None) == 409

    async def scenario():
        await batch.resume(shown["id"], sess)
        await drain()

    asyncio.run(scenario())
    assert [name for name, _ in created] == ["Una", "Tres"]
    assert [p["state"] for p in batch.status(shown["id"], sess)["playlists"]] == ["started", "skipped", "started"]


def test_continuing_after_a_restart_resumes_the_cut_import_instead_of_skipping_it(lab):
    sess, created = lab
    shown = batch.from_spotify(batch.SourceBatch(playlists=[source("Larga", 3), source("Corta", 1)]), sess)

    async def scenario():
        imp._chained.clear()
        await batch.start(shown["id"], batch.Start(selected=[0, 1]), sess)
        # The server stops: the worker task dies while "running" and memory is lost.
        for task in list(imp._chained):
            task.cancel()
        await asyncio.gather(*list(imp._chained), return_exceptions=True)
        imp._imports.clear()
        seen = batch.status(shown["id"], sess)
        assert (seen["status"], seen["reason"]) == ("paused", "interrupted")
        assert [p["state"] for p in seen["playlists"]] == ["running", "waiting"], "a cancelled worker must not advance"
        await batch.resume(shown["id"], sess)
        await drain()

    asyncio.run(scenario())
    assert created == [("Larga", 3), ("Corta", 1)]
    done = batch.status(shown["id"], sess)
    assert done["status"] == "done" and all(p["import"]["status"] == "done" for p in done["playlists"])


def test_a_paused_import_is_not_restarted_by_the_queue(lab):
    sess, created = lab
    shown = batch.from_spotify(batch.SourceBatch(playlists=[source("Pausada", 2), source("Siguiente", 1)]), sess)

    async def scenario():
        await batch.start(shown["id"], batch.Start(selected=[0, 1]), sess)
        for task in list(imp._chained):
            task.cancel()
        await asyncio.gather(*list(imp._chained), return_exceptions=True)
        imp._imports.clear()
        entry = batch._load(shown["id"], "nd:alice-id")["playlists"][0]
        job = imp.owned(entry["importId"], sess)
        job.cancelled = True        # the user paused this import from its own screen
        imp.save(job)
        await batch.resume(shown["id"], sess)
        await drain()

    asyncio.run(scenario())
    assert created == [("Siguiente", 1)]
