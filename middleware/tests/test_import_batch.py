"""«Importar todo»: a ZIP of exported playlists or playlists read after signing in, imported in a chain."""
import asyncio
import io
import zipfile

import pytest
from fastapi import HTTPException

import db
from routes import import_batch as batch
from routes import import_playlist as imp

HEADER = "Track URI,Track Name,Album Name,Artist Name(s),Track Duration (ms),ISRC\n"


def csv(*titles):
    return HEADER + "".join(f"spotify:track:{t},{t},Album,Fixture,200000,\n" for t in titles)


def archive(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return out.getvalue()


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "armonia.db")
    db.init_db()
    sess = db.get_session(db.create_session("alice", "salt", "token", str(tmp_path), library_id=1, user_id="alice-id"))
    other = db.get_session(db.create_session("bob", "salt", "token", str(tmp_path), library_id=1, user_id="bob-id"))
    monkeypatch.setattr(imp, "_imports", {})
    monkeypatch.setenv("MUSIC_YOUTUBE_CAPABILITIES", "stream,persist")
    monkeypatch.delenv("MUSIC_SOURCES_FILE", raising=False)
    playlists, order = {}, []

    async def require(session):
        db.require_active_session(session)
        return 1

    async def find(artist, title, *args):
        return "song-" + title  # every song is already in the library: no provider is needed

    async def scan(*args):
        pass

    async def create(name, ids, *args):
        order.append(name)
        playlists[name] = list(ids)
        return "playlist-" + name

    monkeypatch.setattr(imp.navidrome_client, "require_library_access", require)
    monkeypatch.setattr(imp.navidrome_client, "find_song_id", find)
    monkeypatch.setattr(imp.navidrome_client, "trigger_scan_and_wait", scan)
    monkeypatch.setattr(imp.navidrome_client, "create_playlist", create)
    return sess, other, playlists, order


async def drain():
    while imp._chained:
        await asyncio.gather(*list(imp._chained), return_exceptions=True)


def preview(sess, files):
    return batch._create("zip", batch._parse_zip(archive(files)), sess)


def test_zip_imports_every_selected_playlist_in_order(lab):
    sess, _, playlists, order = lab
    shown = preview(sess, {"viaje_largo.csv": csv("A", "B"), "liked.csv": csv("C"), "notas.txt": "x",
                           "vacia.csv": HEADER})
    assert [(p["name"], p["total"], p["note"]) for p in shown["playlists"]] == [
        ("Viaje largo", 2, None), ("Liked", 1, None), ("Vacia", 0, "unreadable")]
    assert shown["status"] == "preview"

    async def scenario():
        started = await batch.start(shown["id"], batch.Start(selected=[0, 1, 2], names={1: "Me gusta"}), sess)
        assert started["status"] == "running"
        await drain()

    asyncio.run(scenario())
    done = batch.status(shown["id"], sess)
    assert done["status"] == "done"
    assert order == ["Viaje largo", "Me gusta"]
    assert playlists == {"Viaje largo": ["song-A", "song-B"], "Me gusta": ["song-C"]}
    assert [p["state"] for p in done["playlists"]] == ["started", "started", "skipped"]
    assert all(p["import"]["status"] == "done" for p in done["playlists"][:2])
    assert batch.latest(sess)["batch"]["id"] == shown["id"]


def test_only_the_chosen_playlists_are_imported_and_a_batch_starts_once(lab):
    sess, _, playlists, _ = lab
    shown = preview(sess, {"una.csv": csv("A"), "dos.csv": csv("B")})

    async def scenario():
        await batch.start(shown["id"], batch.Start(selected=[1]), sess)
        await drain()
        with pytest.raises(HTTPException) as again:
            await batch.start(shown["id"], batch.Start(selected=[0]), sess)
        assert again.value.status_code == 409

    asyncio.run(scenario())
    assert list(playlists) == ["Dos"]


def test_another_user_cannot_see_start_or_delete_the_batch(lab):
    sess, other, playlists, _ = lab
    shown = preview(sess, {"una.csv": csv("A")})
    for call in (lambda: batch.status(shown["id"], other), lambda: batch.forget(shown["id"], other),
                 lambda: asyncio.run(batch.start(shown["id"], batch.Start(selected=[0]), other)),
                 lambda: asyncio.run(batch.resume(shown["id"], other))):
        with pytest.raises(HTTPException) as denied:
            call()
        assert denied.value.status_code == 404
    assert batch.latest(other)["batch"] is None and not playlists


def test_pause_stops_the_queue_and_resume_continues_it(lab, monkeypatch):
    sess, _, playlists, order = lab
    shown = preview(sess, {"una.csv": csv("A"), "dos.csv": csv("B"), "tres.csv": csv("C")})
    create = imp.navidrome_client.create_playlist

    async def create_then_pause(name, ids, *args):
        if name == "Una":
            batch.pause(shown["id"], sess)
        return await create(name, ids, *args)

    monkeypatch.setattr(imp.navidrome_client, "create_playlist", create_then_pause)

    async def scenario():
        await batch.start(shown["id"], batch.Start(selected=[0, 1, 2]), sess)
        await drain()
        paused = batch.status(shown["id"], sess)
        assert (paused["status"], paused["reason"]) == ("paused", "user") and order == ["Una"]
        assert [p["state"] for p in paused["playlists"]] == ["started", "waiting", "waiting"]
        await batch.resume(shown["id"], sess)
        await drain()

    asyncio.run(scenario())
    assert order == ["Una", "Dos", "Tres"] and batch.status(shown["id"], sess)["status"] == "done"


def test_a_running_import_of_the_user_pauses_the_queue_instead_of_failing_it(lab):
    sess, _, playlists, _ = lab
    shown = preview(sess, {"una.csv": csv("A")})
    busy = imp.ImportJob("other-import", "Otra", 0, username="nd:alice-id")
    busy.status = "running"
    imp._imports[busy.import_id] = busy

    async def scenario():
        state = await batch.start(shown["id"], batch.Start(selected=[0]), sess)
        assert (state["status"], state["reason"]) == ("paused", "busy")
        del imp._imports[busy.import_id]
        await batch.resume(shown["id"], sess)
        await drain()

    asyncio.run(scenario())
    assert list(playlists) == ["Una"]


def test_restart_is_reported_as_interrupted_and_can_continue(lab):
    sess, _, playlists, _ = lab
    shown = preview(sess, {"una.csv": csv("A"), "dos.csv": csv("B")})
    stored = batch._load(shown["id"], "nd:alice-id")
    stored["status"] = "running"
    stored["playlists"][0].update(state="running", importId="lost-with-the-process")
    stored["playlists"][1]["state"] = "waiting"
    batch._save(shown["id"], "nd:alice-id", stored)
    seen = batch.status(shown["id"], sess)
    assert (seen["status"], seen["reason"]) == ("paused", "interrupted")

    async def scenario():
        await batch.resume(shown["id"], sess)
        await drain()

    asyncio.run(scenario())
    assert list(playlists) == ["Dos"]


def test_signed_in_source_builds_the_same_queue(lab):
    sess, _, playlists, _ = lab
    body = batch.SourceBatch(playlists=[
        {"name": "Mías", "tracks": [{"title": "A", "artist": "Fixture", "album": "X", "duration": 200,
                                     "isrc": "ES1", "sourceId": "spotify:track:1"}, {"title": "", "artist": ""}]},
        {"name": "Vacía", "tracks": []}])
    shown = batch.from_spotify(body, sess)
    assert [(p["name"], p["total"], p["note"]) for p in shown["playlists"]] == [("Mías", 2, None), ("Vacía", 0, "empty")]
    stored = batch._load(shown["id"], "nd:alice-id")["playlists"][0]["playlist"]["tracks"]
    assert stored[0]["isrc"] == "ES1" and stored[1]["source_unavailable"] is True

    async def scenario():
        await batch.start(shown["id"], batch.Start(selected=[0, 1]), sess)
        await drain()

    asyncio.run(scenario())
    assert playlists == {"Mías": ["song-A"]}


def test_a_new_proposal_replaces_one_never_started_and_marks_names_already_imported(lab):
    sess, _, _, _ = lab
    first = preview(sess, {"una.csv": csv("A")})

    async def scenario():
        await batch.start(first["id"], batch.Start(selected=[0]), sess)
        await drain()

    asyncio.run(scenario())
    draft = preview(sess, {"una.csv": csv("A"), "dos.csv": csv("B")})
    again = preview(sess, {"una.csv": csv("A"), "dos.csv": csv("B")})
    assert [p["existing"] for p in again["playlists"]] == [True, False]
    with pytest.raises(HTTPException):
        batch.status(draft["id"], sess)
    assert batch.status(first["id"], sess)["status"] == "done"


@pytest.mark.parametrize("content,code", [(b"not a zip", 422), (archive({"leeme.txt": "x"}), 422)])
def test_archives_without_playlists_are_refused(content, code):
    with pytest.raises(HTTPException) as refused:
        batch._parse_zip(content)
    assert refused.value.status_code == code


def test_archive_members_are_bounded_and_never_trusted_for_paths_or_sizes(monkeypatch):
    monkeypatch.setattr(batch, "MAX_MEMBER", 200)
    parsed = batch._parse_zip(archive({"../../etc/escape.csv": csv("A"), "grande.csv": csv(*[f"T{i}" for i in range(40)])}))
    assert [(p["name"], p.get("note")) for p in parsed] == [("Escape", None), ("Grande", "too_large")]
    monkeypatch.setattr(batch, "MAX_PLAYLISTS", 1)
    with pytest.raises(HTTPException) as many:
        batch._parse_zip(archive({"a.csv": csv("A"), "b.csv": csv("B")}))
    assert many.value.status_code == 413


def test_login_identifier_is_per_user_public_and_validated(lab, monkeypatch):
    sess, other, _, _ = lab
    monkeypatch.delenv("MUSIC_SPOTIFY_LOGIN_CLIENT_ID", raising=False)
    assert batch.config(sess) == {"spotifyClientId": "", "fixed": False}
    saved = batch.save_config(batch.LoginConfig(clientId="0123456789abcdef0123456789abcdef"), sess)
    assert saved == {"spotifyClientId": "0123456789abcdef0123456789abcdef", "fixed": False}
    assert batch.config(other)["spotifyClientId"] == ""
    with pytest.raises(ValueError):
        batch.LoginConfig(clientId="not-an-identifier")
    monkeypatch.setenv("MUSIC_SPOTIFY_LOGIN_CLIENT_ID", "f" * 32)
    assert batch.config(other) == {"spotifyClientId": "f" * 32, "fixed": True}
