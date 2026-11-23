import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import BackgroundTasks, HTTPException

import db
from homelab import matcher
from homelab.models import Track
from routes import import_playlist as imp
from routes import playlist_edit

_real_import_playlist_request = imp.navidrome_client.import_playlist_request


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "armonia.db")
    db.init_db()
    sid = db.create_session("alice", "salt", "token", str(tmp_path), library_id=1, user_id="alice-id")
    sess = db.get_session(sid)
    monkeypatch.setattr(imp, "_imports", {})
    monkeypatch.setenv("MUSIC_YOUTUBE_CAPABILITIES", "stream,persist")
    monkeypatch.delenv("MUSIC_SOURCES_FILE", raising=False)
    songs, playlists, downloads = {}, {}, []

    async def require(_):
        db.require_active_session(sess)
        return 1

    async def find(artist, title, *args):
        return songs.get((artist, title))

    async def download(video, artist, title, *args, **options):
        downloads.append(video)
        songs[artist, title] = "local-" + video
        return str(tmp_path / "audio.m4a")

    async def scan(*args):
        pass

    async def create(name, ids, *args):
        ident = f"playlist-{len(playlists)}"
        playlists[ident] = list(ids)
        return ident

    async def owned(ident, session):
        db.require_active_session(session)
        return {"id": ident, "owner": "alice", "entry": [{"id": s} for s in playlists[ident]]}

    async def request(verb, session, pairs):
        db.require_active_session(session)
        ident = dict(pairs)["playlistId"]
        playlists[ident] = [v for k, v in pairs if k == "songId"]
        return {"id": ident}

    monkeypatch.setattr(imp.navidrome_client, "require_library_access", require)
    monkeypatch.setattr(imp.navidrome_client, "find_song_id", find)
    monkeypatch.setattr(imp.navidrome_client, "trigger_scan_and_wait", scan)
    monkeypatch.setattr(imp.navidrome_client, "create_playlist", create)
    monkeypatch.setattr(imp.navidrome_client, "owned_playlist", owned)
    monkeypatch.setattr(imp.navidrome_client, "import_playlist_request", request)
    monkeypatch.setattr(imp, "_download_with_retry", download)
    monkeypatch.setattr(
        imp.ytdlp_service,
        "search",
        lambda *a, **kw: [{"videoId": "abcdefghijk", "title": "Choice", "channel": "Other", "duration": 200}],
    )
    return sess, songs, playlists, downloads


def run(job, sess):
    return asyncio.run(
        imp._run_import(
            job.import_id,
            [i["track"] for i in job.items],
            sess["username"],
            sess["salt"],
            sess["token"],
            sess["library_path"],
            1,
            sess,
        )
    )


def job_for(sess, tracks):
    job = imp.ImportJob("test-import", "Fixture", len(tracks), username="nd:alice-id", durable=True)
    job.items = [imp.new_item(t) for t in tracks]
    imp._imports[job.import_id] = job
    imp.save(job)
    return job


def track(title):
    return {"artist": "Fixture", "title": title, "duration": 200, "album": ""}


def test_partial_manual_restart_order_no_duplicates_two_devices(lab):
    sess, songs, playlists, downloads = lab
    songs["Fixture", "First"] = "first"
    songs["Fixture", "Last"] = "last"
    job = job_for(sess, [track("First"), track("Pending"), track("Last")])
    run(job, sess)
    assert job.status == "done" and job.failed == 1
    pid = job.playlist_id
    assert playlists[pid] == ["first", "last"]
    imp._imports.clear()  # durable recovery after process memory is lost
    job = imp.owned(job.import_id, sess)
    assert job.items[1]["candidates"][0]["track"]["title"] == "Choice"
    stale = job.revision
    bg = BackgroundTasks()
    asyncio.run(
        imp.decide(
            job.import_id, imp.Decision(revision=stale, action="confirm", index=1, source_id="abcdefghijk"), bg, sess
        )
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            imp.decide(job.import_id, imp.Decision(revision=stale, action="skip", index=1), BackgroundTasks(), sess)
        )
    assert error.value.status_code == 409
    asyncio.run(bg())
    assert playlists[pid] == ["first", "local-abcdefghijk", "last"]
    assert len(playlists) == 1 and downloads == ["abcdefghijk"]
    run(job, sess)
    assert len(playlists) == 1 and downloads == ["abcdefghijk"]
    assert job.items[1]["decision"] == "confirmed"
    assert job.items[1]["selected"]["title"] == "Choice"


def test_user_isolation_and_revocation(lab):
    sess, *_ = lab
    job = job_for(sess, [track("Song")])
    bob = db.get_session(db.create_session("bob", "salt", "token", user_id="bob-id"))
    with pytest.raises(HTTPException) as error:
        imp.owned(job.import_id, bob)
    assert error.value.status_code == 404
    assert asyncio.run(imp.list_imports(bob)) == {"imports": []}
    db.delete_session(sess["id"])
    with pytest.raises(HTTPException) as error:
        imp.owned(job.import_id, sess)
    assert error.value.status_code == 401


def test_delete_import_history_preserves_playlist_and_audio(lab):
    sess, songs, playlists, downloads = lab
    songs["Fixture", "Song"] = "song"
    job = job_for(sess, [track("Song")])
    run(job, sess)
    result = asyncio.run(imp.delete_import(job.import_id, imp.DeleteImportRequest(revision=job.revision), sess))
    assert result == {"deleted": True}
    assert songs == {("Fixture", "Song"): "song"}
    assert playlists[job.playlist_id] == ["song"] and not downloads
    assert job.import_id not in imp._imports
    assert asyncio.run(imp.list_imports(sess)) == {"imports": []}
    with pytest.raises(HTTPException) as error:
        imp.owned(job.import_id, sess)
    assert error.value.status_code == 404


def test_delete_import_rejects_other_user_running_stale_and_revoked_sessions(lab):
    sess, *_ = lab
    job = job_for(sess, [track("Song")])
    bob = db.get_session(db.create_session("bob", "salt", "token", user_id="bob-id"))
    request = imp.DeleteImportRequest(revision=job.revision)
    with pytest.raises(HTTPException) as error:
        asyncio.run(imp.delete_import(job.import_id, request, bob))
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        asyncio.run(imp.delete_import(job.import_id, request, sess))
    assert error.value.status_code == 409  # running
    job.status = "done"
    imp.save(job)
    with pytest.raises(HTTPException) as error:
        asyncio.run(imp.delete_import(job.import_id, request, sess))
    assert error.value.status_code == 409  # stale revision
    request = imp.DeleteImportRequest(revision=job.revision)
    db.delete_session(sess["id"])
    with pytest.raises(HTTPException) as error:
        asyncio.run(imp.delete_import(job.import_id, request, sess))
    assert error.value.status_code == 401
    assert job.import_id in imp._imports


def test_revoke_during_search_prevents_audio_and_playlist(lab, monkeypatch):
    sess, songs, playlists, downloads = lab
    job = job_for(sess, [track("Song")])

    def search(*a, **kw):
        db.delete_session(sess["id"])
        return [{"videoId": "abcdefghijk", "title": "Song", "channel": "Fixture", "duration": 200}]

    monkeypatch.setattr(imp.ytdlp_service, "search", search)
    run(job, sess)
    assert job.status == "paused" and not downloads and not playlists


def test_pause_during_provider_and_resume(lab, monkeypatch):
    sess, songs, playlists, downloads = lab
    job = job_for(sess, [track("Song")])

    def search(*a, **kw):
        job.cancelled = True
        return [{"videoId": "abcdefghijk", "title": "Song", "channel": "Fixture", "duration": 200}]

    monkeypatch.setattr(imp.ytdlp_service, "search", search)
    run(job, sess)
    assert job.status == "paused" and not downloads
    job.cancelled = False
    monkeypatch.setattr(imp.ytdlp_service, "search", lambda *a, **kw: [])
    run(job, sess)
    assert job.items[0]["state"] == "not_found"


def test_response_lost_during_create_never_creates_second_playlist(lab, monkeypatch):
    sess, songs, playlists, _ = lab
    songs["Fixture", "Song"] = "song"
    job = job_for(sess, [track("Song")])

    async def lost(*args):
        playlists["remote-created"] = ["song"]
        return None

    monkeypatch.setattr(imp.navidrome_client, "create_playlist", lost)
    run(job, sess)
    assert job.create_intent and job.status == "paused"
    imp._imports.clear()
    job = imp.owned(job.import_id, sess)
    run(job, sess)
    assert len(playlists) == 1 and job.status == "paused"


def test_external_edit_preserved(lab):
    sess, songs, playlists, _ = lab
    songs["Fixture", "Song"] = "song"
    job = job_for(sess, [track("Song")])
    run(job, sess)
    playlists[job.playlist_id].append("edited-elsewhere")
    run(job, sess)
    assert job.status == "paused" and playlists[job.playlist_id] == ["song", "edited-elsewhere"]


def test_indexing_retry_does_not_download_again(lab, monkeypatch):
    sess, songs, playlists, downloads = lab
    job = job_for(sess, [track("Song")])
    job.items[0].update(state="indexing", outcome="downloaded")
    run(job, sess)
    assert job.items[0]["state"] == "indexing" and not downloads
    songs["Fixture", "Song"] = "newly-indexed"
    run(job, sess)
    assert playlists[job.playlist_id] == ["newly-indexed"] and not downloads


def test_change_selected_recording_after_publication_downloads_the_new_choice(lab):
    sess, songs, playlists, downloads = lab
    job = job_for(sess, [track("Original")])
    old = Track(source="youtube", source_id="oldoldold01", artist="Old", title="Old", duration=200).model_dump(mode="json")
    new = Track(source="youtube", source_id="newnewnew01", artist="New", title="New", duration=170).model_dump(mode="json")
    job.items[0].update(state="indexing", outcome="downloaded", decision="confirmed", selected=old,
                        candidates=[{"track": old}, {"track": new}])
    job.status = "done"
    songs["Old", "Old"] = "keep-old-file"
    bg = BackgroundTasks()
    asyncio.run(imp.decide(job.import_id, imp.Decision(revision=job.revision, action="confirm", index=0,
                                                     source_id=new["source_id"]), bg, sess))
    asyncio.run(bg())
    assert downloads == [new["source_id"]]
    assert playlists[job.playlist_id] == ["local-" + new["source_id"]]
    assert songs["Old", "Old"] == "keep-old-file"


def test_confirm_same_published_recording_only_retries_index(lab):
    sess, _, _, downloads = lab
    job = job_for(sess, [track("Original")])
    chosen = Track(source="youtube", source_id="oldoldold01", artist="Old", title="Old", duration=200).model_dump(mode="json")
    job.items[0].update(state="indexing", outcome="downloaded", decision="confirmed", selected=chosen,
                        candidates=[{"track": chosen}])
    job.status = "done"
    bg = BackgroundTasks()
    asyncio.run(imp.decide(job.import_id, imp.Decision(revision=job.revision, action="confirm", index=0,
                                                     source_id=chosen["source_id"]), bg, sess))
    asyncio.run(bg())
    assert not downloads and job.items[0]["state"] == "indexing"


def test_search_after_publication_reaches_provider_instead_of_waiting_for_index(lab, monkeypatch):
    sess, _, _, downloads = lab
    job = job_for(sess, [track("Original")])
    job.items[0].update(state="indexing", outcome="downloaded", decision="confirmed",
                        selected={"source": "youtube", "source_id": "oldoldold01", "artist": "Old", "title": "Old"})
    job.status = "done"
    calls = []

    async def resolve(wanted, active, query):
        calls.append(query)
        return {"attempts": [], "provider_errors": [], "selected": None, "candidates": []}

    monkeypatch.setattr(imp.import_search, "resolve", resolve)
    bg = BackgroundTasks()
    asyncio.run(imp.decide(job.import_id, imp.Decision(revision=job.revision, action="search", index=0,
                                                     query="A better choice"), bg, sess))
    asyncio.run(bg())
    assert calls == ["A better choice"] and not downloads
    assert job.items[0]["state"] == "not_found"


def test_playlist_outage_reports_stage_and_resume_preserves_ready_tracks(lab, monkeypatch):
    sess, songs, playlists, downloads = lab
    songs["Fixture", "First"] = "first"
    job = job_for(sess, [track("First"), track("Second")])
    run(job, sess)
    pid = job.playlist_id
    job.items[1].update(state="ready", song_id="second", outcome="existing")
    imp.save(job)
    request = imp.navidrome_client.import_playlist_request

    async def unavailable(*args):
        raise HTTPException(502, "upstream unavailable")

    monkeypatch.setattr(imp.navidrome_client, "import_playlist_request", unavailable)
    run(job, sess)
    assert job.error == "playlist_service_unavailable" and job.status == "paused"
    assert playlists[pid] == ["first"] and not downloads
    monkeypatch.setattr(imp.navidrome_client, "import_playlist_request", request)
    bg = BackgroundTasks()
    asyncio.run(imp.decide(job.import_id, imp.Decision(revision=job.revision, action="resume"), bg, sess))
    asyncio.run(bg())
    assert job.error is None and playlists[pid] == ["first", "second"] and not downloads


def test_navidrome_missing_playlist_code_is_not_an_outage(lab, monkeypatch):
    sess, *_ = lab

    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200,
            json={"subsonic-response": {"status": "failed", "error": {"code": 70, "message": "not found"}}}))) as c:
            yield c

    from services import navidrome_client as nd
    monkeypatch.setattr(nd, "_client", client)
    with pytest.raises(HTTPException) as error:
        asyncio.run(_real_import_playlist_request("getPlaylist", sess, [("id", "missing")]))
    assert error.value.status_code == 404 and error.value.detail == "playlist not found"


def test_missing_destination_requires_explicit_recovery_preserves_order_and_duplicates(lab, monkeypatch):
    sess, songs, playlists, downloads = lab
    songs["Fixture", "First"] = "first"
    job = job_for(sess, [track("First"), track("First")])
    run(job, sess)
    pid = job.playlist_id
    del playlists[pid]  # isolated fixture only
    original_owned = imp.navidrome_client.owned_playlist

    async def owned(ident, session):
        if ident not in playlists:
            raise HTTPException(404, "playlist not found")
        return await original_owned(ident, session)

    monkeypatch.setattr(imp.navidrome_client, "owned_playlist", owned)
    run(job, sess)
    assert job.error == "playlist_missing" and job.status == "paused"
    assert not playlists and not downloads
    # Ordinary resume does not silently recreate a user-deleted playlist.
    bg = BackgroundTasks()
    asyncio.run(imp.decide(job.import_id, imp.Decision(revision=job.revision, action="resume"), bg, sess))
    asyncio.run(bg())
    assert job.error == "playlist_missing" and not playlists
    stale = job.revision
    bg = BackgroundTasks()
    asyncio.run(imp.decide(job.import_id, imp.Decision(revision=stale, action="create_new"), bg, sess))
    with pytest.raises(HTTPException) as conflict:
        asyncio.run(imp.decide(job.import_id, imp.Decision(revision=stale, action="create_new"), BackgroundTasks(), sess))
    assert conflict.value.status_code == 409
    asyncio.run(bg())
    assert job.status == "done" and job.error is None
    assert len(playlists) == 1 and playlists[job.playlist_id] == ["first", "first"] and not downloads


@pytest.mark.parametrize("upstream_code", [403, 502, None])
def test_create_new_never_replaces_existing_or_inaccessible_destination(lab, monkeypatch, upstream_code):
    sess, songs, playlists, downloads = lab
    songs["Fixture", "First"] = "first"
    job = job_for(sess, [track("First")])
    run(job, sess)
    job.error = "playlist_missing"  # stale client/server observation
    pid = job.playlist_id
    original_owned = imp.navidrome_client.owned_playlist

    async def owned(ident, session):
        if upstream_code:
            raise HTTPException(upstream_code, "unavailable")
        return await original_owned(ident, session)

    monkeypatch.setattr(imp.navidrome_client, "owned_playlist", owned)
    with pytest.raises(HTTPException):
        asyncio.run(imp.decide(job.import_id, imp.Decision(revision=job.revision, action="create_new"), BackgroundTasks(), sess))
    assert job.playlist_id == pid and len(playlists) == 1 and not downloads


def test_manual_search_never_autoselects_and_skip_is_durable(lab, monkeypatch):
    sess, *_ = lab
    job = job_for(sess, [track("Song")])
    run(job, sess)
    monkeypatch.setattr(
        imp.ytdlp_service,
        "search",
        lambda *a, **kw: [{"videoId": "abcdefghijk", "title": "Song", "channel": "Fixture", "duration": 200}],
    )
    bg = BackgroundTasks()
    asyncio.run(
        imp.decide(
            job.import_id,
            imp.Decision(revision=job.revision, action="search", index=0, query="different query"),
            bg,
            sess,
        )
    )
    asyncio.run(bg())
    assert job.items[0]["state"] == "review" and not job.items[0]["selected"]
    asyncio.run(
        imp.decide(job.import_id, imp.Decision(revision=job.revision, action="skip", index=0), BackgroundTasks(), sess)
    )
    imp._imports.clear()
    job = imp.owned(job.import_id, sess)
    assert job.items[0]["decision"] == "skipped"


def test_legacy_attach_uses_existing_playlist_without_downloading(lab, monkeypatch):
    sess, songs, playlists, downloads = lab

    async def fetch(*args):
        return {"name": "Legacy", "tracks": [track("First"), track("Pending"), track("Last")]}

    async def owned(*args):
        return {
            "id": "legacy",
            "owner": "alice",
            "entry": [dict(track("First"), id="first"), dict(track("Last"), id="last")],
        }

    monkeypatch.setattr(imp.spotify_client, "fetch_playlist", fetch)
    monkeypatch.setattr(imp.navidrome_client, "owned_playlist", owned)
    playlists["legacy"] = ["first", "last"]
    bg = BackgroundTasks()
    result = asyncio.run(
        imp.import_spotify(imp.ImportRequest(url="spotify:playlist:fixture", playlistId="legacy"), bg, sess)
    )
    asyncio.run(bg())
    job = imp.owned(result["importId"], sess)
    assert job.playlist_id == "legacy" and job.review_only and not downloads
    assert [i["state"] for i in job.items] == ["ready", "review", "ready"]
    assert list(playlists) == ["legacy"]


def test_native_playlist_edit_conflict_and_idempotency(lab):
    sess, _, playlists, _ = lab
    playlists["native"] = ["a", "b"]
    body = playlist_edit.Edit(expected=["a", "b"], songs=["b", "a"])
    asyncio.run(playlist_edit.edit("native", body, sess))
    asyncio.run(playlist_edit.edit("native", body, sess))
    with pytest.raises(HTTPException) as error:
        asyncio.run(playlist_edit.edit("native", playlist_edit.Edit(expected=["a", "b"], songs=["c"]), sess))
    assert error.value.status_code == 409 and playlists["native"] == ["b", "a"]


@pytest.mark.parametrize(
    "artist,title,allowed",
    [
        ("B, A", "Song", True),
        ("A", "Song (feat. B)", True),
        # A collaborator omitted or added by the source: accepted on main artist, title and duration.
        ("A", "Song", True),
        ("A, B, C", "Song", True),
        ("C, A, B", "Song", False),
        ("C", "Song", False),
        ("B, A", "Song (Live)", False),
        ("A", "Song (feat. B) Remix", False),
    ],
)
def test_credits_need_equality_or_collaborator_evidence(artist, title, allowed):
    wanted = {"artist": "A, B", "title": "Song", "duration": 200}
    candidate = Track(source="youtube", source_id="abcdefghijk", title=title, artist=artist, duration=200)
    assert bool(matcher.rank(wanted, [candidate])["selected"]) == allowed


def test_attach_lost_create_response_keeps_manual_decisions(lab):
    sess, _, playlists, _ = lab
    job = job_for(sess, [track("Song")])
    job.items[0].update(state="ready", song_id="saved", decision="confirmed")
    job.status = "paused"
    job.error = "playlist creation uncertain"
    job.create_intent = True
    imp.save(job)
    playlists["created-before-crash"] = ["saved"]
    result = asyncio.run(
        imp.attach_existing(
            job.import_id, imp.AttachRequest(revision=job.revision, playlistId="created-before-crash"), sess
        )
    )
    assert result["playlistId"] == "created-before-crash"
    imp._imports.clear()
    restored = imp.owned(job.import_id, sess)
    assert restored.items[0]["decision"] == "confirmed"
    assert restored.playlist_id == "created-before-crash"


def test_pause_at_publication_guard_prevents_rename(lab, monkeypatch):
    sess, _, _, _ = lab
    # Exercise the real retry wrapper and final guard, with no external audio.
    cancelled = False
    sess["import_cancel_check"] = lambda: cancelled

    async def download(*args, **kwargs):
        nonlocal cancelled
        await kwargs["authorize"]()
        cancelled = True
        with kwargs["final_guard"]():
            pytest.fail("publication must not be reached")

    monkeypatch.setattr(imp.ytdlp_service, "download_limited", download)
    # lab replaces the wrapper; retrieve its actual module source function.
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("guard_import_test", imp.__file__)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    with pytest.raises(imp.ytdlp_service.DownloadCancelled):
        asyncio.run(module._download_with_retry("abcdefghijk", "Fixture", "Song", sess["library_path"], sess))


def test_saved_publication_not_indexed_is_rescanned_without_second_write(lab, monkeypatch):
    sess, songs, playlists, downloads = lab
    job = job_for(sess, [track("Song")])
    job.items[0].update(
        state="downloading",
        selected=Track(
            source="youtube", source_id="abcdefghijk", title="Song", artist="Fixture", duration=200
        ).model_dump(mode="json"),
    )
    attempts = []

    async def receipt(*args, **options):
        attempts.append(1)
        raise HTTPException(409, "recording already saved; rescan your library")

    scans = []

    async def scan(*args):
        scans.append(1)
        if len(scans) == 2:
            songs["Fixture", "Song"] = "published-before-crash"

    monkeypatch.setattr(imp, "_download_with_retry", receipt)
    monkeypatch.setattr(imp.navidrome_client, "trigger_scan_and_wait", scan)
    run(job, sess)
    assert playlists[job.playlist_id] == ["published-before-crash"]
    assert not downloads and len(attempts) == 1


def test_provider_failure_is_distinct_from_no_results(lab, monkeypatch):
    sess, _, _, _ = lab
    job = job_for(sess, [track("Song")])

    def timeout(*args, **kwargs):
        raise TimeoutError("fictional provider timeout")

    monkeypatch.setattr(imp.ytdlp_service, "search", timeout)
    run(job, sess)
    assert job.items[0]["state"] == "search_failed"
    assert job.items[0]["reason"] == "provider_unavailable"


def test_paused_status_keeps_android_contract(lab):
    sess, _, _, _ = lab
    job = job_for(sess, [track("Song")])
    job.status = "paused"
    assert imp.result(job)["status"] == "error"
    assert imp.result(job)["resumeAvailable"] is True


def test_removing_final_native_songs_uses_explicit_positions(lab, monkeypatch):
    sess, _, playlists, _ = lab
    playlists["native"] = ["a", "b"]
    calls = []

    async def request(verb, session, pairs):
        calls.append((verb, pairs))
        return {}

    monkeypatch.setattr(imp.navidrome_client, "import_playlist_request", request)
    asyncio.run(playlist_edit.edit("native", playlist_edit.Edit(expected=["a", "b"], songs=[]), sess))
    assert calls == [
        ("updatePlaylist", [("playlistId", "native"), ("songIndexToRemove", "1"), ("songIndexToRemove", "0")])
    ]


@pytest.mark.parametrize(
    "duration,album,expected",
    [(200, "Studio", "local"), (240, "Studio", None), (None, "Studio", None), (200, "Live", None)],
)
def test_import_local_reuse_requires_recording_evidence(lab, monkeypatch, duration, album, expected):
    # Fixture replaces find_song_id for workflow tests; reload just this module
    # under a different name to exercise the actual lookup implementation.
    import importlib.util

    from services import navidrome_client as nd

    spec = importlib.util.spec_from_file_location("lookup_import_test", nd.__file__)
    actual = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(actual)

    async def search(*args):
        return [{"id": "local", "title": "Song", "artist": "Fixture", "album": album, "duration": duration}]

    monkeypatch.setattr(actual, "search_songs", search)
    assert asyncio.run(actual.find_song_id("Fixture", "Song", "fixture", "s", "t", track("Song"))) == expected


def test_source_resume_preserves_positions_repeats_decisions_and_playlist(lab, monkeypatch):
    sess, songs, playlists, downloads = lab
    songs['Fixture', 'First'] = 'first'
    job = job_for(sess, [track('First'), track('Pending'), track('First')])
    job.source_url = 'spotify:playlist:fixture'
    run(job, sess)
    pid = job.playlist_id
    job.items[1].update(state='skipped', decision='skipped')
    async def fetch(url):
        return {'name':'Fixture', 'tracks':[track('First'),track('Pending'),track('First'),track('Last')],
                'source_total':4,'source_complete':True}
    monkeypatch.setattr(imp.spotify_client, 'fetch_playlist', fetch)
    songs['Fixture', 'Last'] = 'last'
    bg = BackgroundTasks()
    asyncio.run(imp.decide(job.import_id, imp.Decision(revision=job.revision, action='refresh_source'), bg, sess))
    asyncio.run(bg())
    assert playlists[pid] == ['first', 'first', 'last'] and len(playlists) == 1
    assert job.items[1]['decision'] == 'skipped' and not downloads
    imp._imports.clear()
    restored = imp.owned(job.import_id, sess)
    assert restored.source_info['source_complete'] and restored.total == 4


def test_source_changed_is_rejected_without_playlist_mutation(lab, monkeypatch):
    sess, songs, playlists, _ = lab
    songs['Fixture','First'] = 'first'
    job = job_for(sess, [track('First')])
    run(job,sess)
    async def fetch(url):
        return {'tracks':[track('Other')]}
    monkeypatch.setattr(imp.spotify_client, 'fetch_playlist', fetch)
    with pytest.raises(HTTPException):
        asyncio.run(imp.decide(job.import_id, imp.Decision(revision=job.revision, action='refresh_source'), BackgroundTasks(),sess))
    assert playlists[job.playlist_id] == ['first'] and job.items[0]['track']['title'] == 'First'


@pytest.mark.parametrize('state', ['ready', 'skipped'])
def test_recovered_metadata_keeps_manual_decisions_at_unavailable_positions(lab, monkeypatch, state):
    sess, _, playlists, downloads = lab
    job = job_for(sess, [{**track('Unavailable'), 'source_unavailable':True, 'source_id':'spotify:track:fixture'}])
    job.items[0].update(state=state, decision='confirmed' if state=='ready' else 'skipped',
                        selected={**track('User choice'),'source':'youtube','source_id':'abcdefghijk'},
                        song_id='chosen' if state=='ready' else None)
    run(job,sess)
    async def fetch(url):
        return {'tracks':[{**track('Recovered'),'source_id':'spotify:track:fixture'}], 'source_complete':True, 'source_total':1}
    monkeypatch.setattr(imp.spotify_client,'fetch_playlist',fetch)
    bg=BackgroundTasks()
    asyncio.run(imp.decide(job.import_id,imp.Decision(revision=job.revision,action='refresh_source'),bg,sess))
    asyncio.run(bg())
    assert job.items[0]['state']==state and job.items[0]['selected']['title']=='User choice'
    assert job.items[0]['track']['title']=='Recovered' and not downloads
    if state=='ready':
        assert playlists[job.playlist_id]==['chosen']


def export(titles):
    return 'Track URI,Track Name,Artist Name(s),Duration (ms)\n' + ''.join(
        f'spotify:track:{t},{t},Fixture;Guest,200000\n' for t in titles)


def test_partial_view_is_completed_from_the_owner_export_without_duplicates(lab, monkeypatch):
    sess, songs, playlists, downloads = lab
    for title in ('A', 'B', 'C', 'D'):
        songs['Fixture, Guest', title] = songs['Fixture', title] = title.lower()
    # The public view returned the first two of four songs (one repeated on purpose later).
    job = job_for(sess, [{**track('A'), 'source_id': 'spotify:track:A'}, {**track('B'), 'source_id': 'spotify:track:B'}])
    job.source_url = 'spotify:playlist:fixture'
    job.source_info = {'source_complete': False, 'source_total': None, 'retrieved': 2, 'source_warning': 'embed_partial_or_unknown'}
    run(job, sess)
    pid = job.playlist_id
    assert playlists[pid] == ['a', 'b'] and imp.result(job)['notRetrieved'] is None
    async def forbidden(url):
        raise AssertionError('the file replaces the network fetch')
    monkeypatch.setattr(imp.spotify_client, 'fetch_playlist', forbidden)
    # A file of another list is refused and nothing changes.
    with pytest.raises(HTTPException) as other:
        asyncio.run(imp.decide(job.import_id, imp.Decision(revision=job.revision, action='refresh_source',
                                                           content=export(['A', 'X', 'C'])), BackgroundTasks(), sess))
    assert other.value.status_code == 409 and playlists[pid] == ['a', 'b'] and job.total == 2
    bg = BackgroundTasks()
    asyncio.run(imp.decide(job.import_id, imp.Decision(revision=job.revision, action='refresh_source',
                                                       content=export(['A', 'B', 'C', 'A', 'D'])), bg, sess))
    asyncio.run(bg())
    assert playlists[pid] == ['a', 'b', 'c', 'a', 'd'] and len(playlists) == 1 and not downloads
    done = imp.result(job)
    assert done['total'] == 5 and done['notRetrieved'] == 0 and done['sourceInfo']['source_complete']
    assert done['sourceInfo']['metadata_source'] == 'file'
    # Repeating the same file adds nothing.
    bg = BackgroundTasks()
    asyncio.run(imp.decide(job.import_id, imp.Decision(revision=job.revision, action='refresh_source',
                                                       content=export(['A', 'B', 'C', 'A', 'D'])), bg, sess))
    asyncio.run(bg())
    assert playlists[pid] == ['a', 'b', 'c', 'a', 'd']


def test_file_import_into_an_existing_playlist_keeps_what_is_there(lab, monkeypatch):
    sess, songs, playlists, downloads = lab
    for title in ('A', 'B', 'C'):
        songs['Fixture, Guest', title] = title.lower()
    playlists['old'] = ['a', 'b']
    async def owned(ident, session):
        return {'id': ident, 'owner': 'alice', 'entry': [{'id': 'a', 'title': 'A', 'artist': 'Fixture'},
                                                         {'id': 'b', 'title': 'B', 'artist': 'Fixture'}]}
    monkeypatch.setattr(imp.navidrome_client, 'owned_playlist', owned)
    bg = BackgroundTasks()
    started = asyncio.run(imp.import_file(imp.FileImportRequest(name='Mi lista', content=export(['A', 'B', 'C']), playlistId='old'), bg, sess))
    assert started['total'] == 3
    job = imp._imports[started['importId']]
    assert [i['state'] for i in job.items] == ['ready', 'ready', 'pending'] and job.playlist_id == 'old'
    with pytest.raises(HTTPException) as bad:
        asyncio.run(imp.import_file(imp.FileImportRequest(name='x', content='sin separador'), BackgroundTasks(), sess))
    assert bad.value.status_code == 400


@pytest.mark.parametrize("duration,second,allowed", [(200.4, None, True), (203, None, False), (None, None, False),
                                                    (200, 200.5, False), (200, 230, True)])
def test_collaborator_credits_need_tight_duration_and_a_single_candidate(duration, second, allowed):
    wanted = {"artist": "Hard, Nik, Dualy", "title": "Lo Real", "duration": 200}
    candidates = [Track(source="youtube", source_id="abcdefghijk", title="Lo Real", artist="Hard, Nik", duration=duration),
                  Track(source="youtube", source_id="remixremix1", title="Lo Real (Remix)", artist="Hard, Nik, Dualy", duration=200)]
    if second:
        candidates.append(Track(source="youtube", source_id="otherupload", title="Lo Real", artist="Hard", duration=second))
    selected = matcher.rank(wanted, candidates)["selected"]
    assert bool(selected) == allowed and (not selected or selected["source_id"] == "abcdefghijk")


def _t(ident, title, artist, duration):
    return Track(source="youtube", source_id=ident, title=title, artist=artist, duration=duration)


def test_real_review_cases_from_the_user_import():
    """Shapes preserved from a real import that were left for manual review (names as published)."""
    # A sequel with another title does not make the exact song ambiguous.
    demons = matcher.rank({"artist": "Nadal015, Miranda", "title": "Demons", "duration": 236.03, "album": ""}, [
        _t("aaaaaaaaaa1", "Demons", "Nadal015, Miranda", 237), _t("aaaaaaaaaa2", "Demons II", "Nadal015, Miranda", 235)])
    assert demons["selected"]["source_id"] == "aaaaaaaaaa1"
    # ...but two uploads that are both exact still need the listener.
    twice = matcher.rank({"artist": "Nadal015, Miranda", "title": "Demons", "duration": 236.03, "album": ""}, [
        _t("aaaaaaaaaa1", "Demons", "Nadal015, Miranda", 237), _t("aaaaaaaaaa3", "Demons", "Nadal015, Miranda", 236)])
    assert twice["selected"] is None
    # The provider lists a collaborator the playlist omits; title and duration agree.
    lil = matcher.rank({"artist": "Hard GZ", "title": "Lil GZ 1995", "duration": 151.723, "album": ""}, [
        _t("bbbbbbbbbb1", "Lil GZ 1995", "Hard GZ, LIL GZ", 152), _t("bbbbbbbbbb2", "DOPE", "Lil GZ, Hard GZ, Lupita's Friends", 153)])
    assert lil["selected"]["source_id"] == "bbbbbbbbbb1"
    # An accent destroyed by the publisher's text encoding.
    broken = matcher.rank({"artist": "Denom, Costa", "title": "Mi Propia Inversión", "duration": 240.85, "album": ""}, [
        _t("cccccccccc1", "Mi Propia Inversi—n", "Denom feat Costa", 241), _t("cccccccccc2", "Mi Prision", "Costa, Carmona", 241)])
    assert broken["selected"]["source_id"] == "cccccccccc1" and broken["candidates"][0]["evidence"] == "garbled_title"
    ellipsis = matcher.rank({"artist": "Denom, Recycled J", "title": "Ya Sabes Lo Que…", "duration": 191.872, "album": ""}, [
        _t("dddddddddd1", "Ya Sabes Lo QueÉ", "Denom feat Recycled J", 192)])
    assert ellipsis["selected"]["source_id"] == "dddddddddd1"


@pytest.mark.parametrize("title,artist,duration", [
    ("Mi Propia Inversion II", "Denom feat Costa", 241),   # another title, not a damaged character
    ("Mi Propia Inversi—n", "Denom feat Costa", 247),       # duration does not confirm it
    ("Mi Propia Inversi—n", "Otro Artista", 241),           # other credits
    ("Mi Propia Inversian", "Denom feat Costa", 241),       # a different letter is a different word
])
def test_damaged_title_needs_credits_and_duration(title, artist, duration):
    wanted = {"artist": "Denom, Costa", "title": "Mi Propia Inversión", "duration": 240.85, "album": ""}
    assert matcher.rank(wanted, [_t("cccccccccc1", title, artist, duration)])["selected"] is None
    assert not matcher.score({"artist": "A", "title": "Añ", "duration": 1}, _t("eeeeeeeeee1", "A—", "A", 1))["title_garbled"]


def test_resume_judges_stored_review_items_again_but_never_a_manual_decision(lab):
    sess, songs, playlists, downloads = lab
    wanted = {"artist": "Hard GZ", "title": "Lil GZ 1995", "duration": 151.723, "album": ""}
    stored = [{"track": _t("bbbbbbbbbb1", "Lil GZ 1995", "Hard GZ, LIL GZ", 152).model_dump(mode="json"), "score": 78.3,
               "reasons": ["title or artist is not exact enough"]}]
    job = job_for(sess, [wanted, dict(wanted, title="Otra"), dict(wanted, title="Saltada")])
    job.items[0].update(state="review", candidates=stored)
    job.items[1].update(state="review", candidates=[{"track": _t("zzzzzzzzzz1", "Distinta", "Nadie", 300).model_dump(mode="json"),
                                                     "score": 10, "reasons": ["duration differs"]}])
    job.items[2].update(state="skipped", decision="skipped", candidates=stored)
    job.status = "done"
    imp.save(job)
    bg = BackgroundTasks()
    asyncio.run(imp.decide(job.import_id, imp.Decision(revision=job.revision, action="resume"), bg, sess))
    assert job.items[0]["selected"]["source_id"] == "bbbbbbbbbb1" and job.items[0]["state"] == "pending"
    assert job.items[1]["state"] == "review" and not job.items[1].get("selected")
    assert job.items[2]["state"] == "skipped"


def test_rereading_a_source_without_a_spotify_link_is_explained_not_a_server_error(lab, monkeypatch):
    """Regression: four 500s in the live log when completing an import that had no link."""
    sess, songs, playlists, _ = lab
    songs['Fixture', 'First'] = 'first'
    job = job_for(sess, [track('First')])
    run(job, sess)
    async def fetch(url):
        raise imp.SpotifyError("That doesn't look like a Spotify playlist link")
    monkeypatch.setattr(imp.spotify_client, 'fetch_playlist', fetch)
    with pytest.raises(HTTPException) as error:
        asyncio.run(imp.decide(job.import_id, imp.Decision(revision=job.revision, action='refresh_source'), BackgroundTasks(), sess))
    assert error.value.status_code == 400 and job.status == 'paused'


def test_search_advances_while_download_slots_are_busy(lab, monkeypatch):
    sess, _, playlists, _ = lab
    job = job_for(sess, [track(str(i)) for i in range(5)])
    found_all = asyncio.Event()
    searched = []
    real_download = imp._download_with_retry

    async def resolve(track, active, query):
        searched.append(track["title"])
        if len(searched) == len(job.items):
            found_all.set()
        return {"attempts": [], "provider_errors": 0, "candidates": [],
                "selected": {"source_id": "video00000" + track["title"], "album": ""}}

    async def wait_for_search(*args, **kw):
        await asyncio.wait_for(found_all.wait(), timeout=2)
        return await real_download(*args, **kw)

    monkeypatch.setattr(imp.import_search, "resolve", resolve)
    monkeypatch.setattr(imp, "_download_with_retry", wait_for_search)
    run(job, sess)
    assert playlists[job.playlist_id] == [f"local-video00000{i}" for i in range(5)]
