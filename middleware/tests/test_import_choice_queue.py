import asyncio
import json

import pytest
from fastapi import BackgroundTasks, HTTPException
from test_import_review import job_for, run, track
from test_import_review import lab as lab

import db
from routes import import_playlist as imp


def review_job(sess, count=3):
    job = job_for(sess, [track(f"Song {i}") for i in range(count)])
    for i, item in enumerate(job.items):
        candidate = {**item["track"], "source": "youtube", "source_id": f"choice{i:05d}"}
        item.update(state="review", candidates=[{"track": candidate, "score": 80, "reasons": []}])
    job.status = "done"
    job.phase = "review"
    imp.save(job)
    return job


def confirm(job, i, revision=None, item_revision=None):
    return imp.Decision(revision=job.revision if revision is None else revision, action="confirm", index=i,
                        source_id=f"choice{i:05d}",
                        itemRevision=job.items[i].get("choice_revision", 0) if item_revision is None else item_revision)


def test_confirm_next_position_without_waiting_for_download_and_preserve_order(lab, monkeypatch):
    sess, songs, playlists, downloads = lab
    job = review_job(sess)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        original = imp._download_with_retry

        async def slow(video, *args, **options):
            if video == "choice00000":
                entered.set()
                await release.wait()
            return await original(video, *args, **options)

        monkeypatch.setattr(imp, "_download_with_retry", slow)
        stale_job_revision = job.revision
        bg = BackgroundTasks()
        first = await imp.decide(job.import_id, confirm(job, 0), bg, sess)
        assert first["acceptingDecisions"] and first["items"][0]["state"] == "pending"
        worker = asyncio.create_task(bg())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            no_second_worker = BackgroundTasks()
            second = await asyncio.wait_for(imp.decide(
                job.import_id, confirm(job, 1, revision=stale_job_revision), no_second_worker, sess), 1)
            assert second["items"][1]["state"] == "pending" and not downloads
            assert not no_second_worker.tasks
            # The same old screen may skip another position, but cannot override a queued choice.
            await imp.decide(job.import_id, imp.Decision(revision=stale_job_revision, itemRevision=0,
                                                        action="skip", index=2), BackgroundTasks(), sess)
            with pytest.raises(HTTPException) as error:
                await imp.decide(job.import_id, confirm(job, 1, item_revision=0), BackgroundTasks(), sess)
            assert error.value.status_code == 409
        finally:
            release.set()
            await asyncio.wait_for(worker, 2)
        assert downloads == ["choice00000", "choice00001"]
        assert playlists[job.playlist_id] == ["local-choice00000", "local-choice00001"]
        assert job.items[2]["state"] == "skipped" and job.status == "done"

    asyncio.run(scenario())


def test_choice_arriving_during_playlist_publication_is_drained_without_duplicate_playlist(lab, monkeypatch):
    sess, songs, playlists, downloads = lab
    job = review_job(sess, 2)

    async def scenario():
        publishing, release = asyncio.Event(), asyncio.Event()
        create = imp.navidrome_client.create_playlist

        async def slow_create(*args):
            publishing.set()
            await release.wait()
            return await create(*args)

        monkeypatch.setattr(imp.navidrome_client, "create_playlist", slow_create)
        bg = BackgroundTasks()
        await imp.decide(job.import_id, confirm(job, 0), bg, sess)
        worker = asyncio.create_task(bg())
        try:
            await asyncio.wait_for(publishing.wait(), 1)
            await imp.decide(job.import_id, confirm(job, 1), BackgroundTasks(), sess)
        finally:
            release.set()
            await asyncio.wait_for(worker, 2)
        assert len(playlists) == 1
        assert playlists[job.playlist_id] == ["local-choice00000", "local-choice00001"]
        assert downloads == ["choice00000", "choice00001"]

    asyncio.run(scenario())


def test_choices_survive_restart_before_audio_and_failed_choice_remains_retryable(lab, monkeypatch):
    sess, songs, playlists, downloads = lab
    job = review_job(sess, 2)
    asyncio.run(imp.decide(job.import_id, confirm(job, 0), BackgroundTasks(), sess))
    imp._imports.clear()
    job = imp.owned(job.import_id, sess)
    assert job.status == "paused" and job.items[0]["decision"] == "confirmed"
    assert job.items[0]["choice_revision"] == 1
    assert not job.review_accepting

    original = imp._download_with_retry
    async def unavailable(*args, **options):
        raise RuntimeError("fictional provider unavailable")

    monkeypatch.setattr(imp, "_download_with_retry", unavailable)
    run(job, sess)
    failed = imp.result(job)["items"][0]
    assert failed["state"] == "download_failed" and failed["reviewOrder"] > 0
    assert failed["reason"] == "provider_unavailable" and failed["selected"]["source_id"] == "choice00000"
    assert job.items[1].get("review_order", 0) == 0
    monkeypatch.setattr(imp, "_download_with_retry", original)
    bg = BackgroundTasks()
    asyncio.run(imp.decide(job.import_id, imp.Decision(revision=0, itemRevision=failed["choiceRevision"],
                                                     action="retry", index=0), bg, sess))
    asyncio.run(bg())
    assert job.items[0]["state"] == "ready" and downloads == ["choice00000"]


def test_active_queue_rejects_wrong_owner_revoked_session_and_cancelled_worker(lab):
    sess, *_ = lab
    job = review_job(sess, 2)
    asyncio.run(imp.decide(job.import_id, confirm(job, 0), BackgroundTasks(), sess))
    bob = db.get_session(db.create_session("bob", "salt", "token", user_id="bob-id"))
    with pytest.raises(HTTPException) as error:
        asyncio.run(imp.decide(job.import_id, confirm(job, 1), BackgroundTasks(), bob))
    assert error.value.status_code == 404
    asyncio.run(imp.cancel(job.import_id, sess))
    assert not imp.result(job)["acceptingDecisions"]
    with pytest.raises(HTTPException) as error:
        asyncio.run(imp.decide(job.import_id, confirm(job, 1), BackgroundTasks(), sess))
    assert error.value.status_code == 409
    db.delete_session(sess["id"])
    with pytest.raises(HTTPException) as error:
        asyncio.run(imp.decide(job.import_id, confirm(job, 1), BackgroundTasks(), sess))
    assert error.value.status_code == 401
    assert job.items[1]["state"] == "review"


def test_old_clients_still_conflict_while_running_and_source_reservations_stay_exclusive(lab):
    sess, *_ = lab
    job = review_job(sess)
    job.status = "running"
    job.review_accepting = False
    for item_revision in (None, 0):
        with pytest.raises(HTTPException) as error:
            asyncio.run(imp.decide(job.import_id, imp.Decision(revision=job.revision, itemRevision=item_revision,
                                                              action="confirm", index=0, source_id="choice00000"),
                                   BackgroundTasks(), sess))
        assert error.value.status_code == 409


def test_durable_payload_does_not_add_transient_top_level_fields(lab):
    sess, *_ = lab
    job = review_job(sess, 1)
    asyncio.run(imp.decide(job.import_id, confirm(job, 0), BackgroundTasks(), sess))
    with db._conn() as connection:
        payload = json.loads(connection.execute("SELECT payload FROM playlist_imports WHERE id=?", (job.import_id,)).fetchone()[0])
    assert "review_accepting" not in payload
    assert payload["items"][0]["choice_revision"] == 1
    assert payload["items"][0]["decision"] == "confirmed"


def test_confirmed_index_pending_exposes_recoverable_problem_without_second_download(lab, monkeypatch):
    sess, songs, playlists, downloads = lab
    job = review_job(sess, 1)
    original_find = imp.navidrome_client.find_song_id
    async def not_indexed(*args):
        return None
    monkeypatch.setattr(imp.navidrome_client, "find_song_id", not_indexed)
    bg = BackgroundTasks()
    asyncio.run(imp.decide(job.import_id, confirm(job, 0), bg, sess))
    asyncio.run(bg())
    item = imp.result(job)["items"][0]
    assert item["state"] == "indexing" and item["reviewOrder"] > 0
    assert item["reason"] == "index_pending"
    monkeypatch.setattr(imp.navidrome_client, "find_song_id", original_find)
    bg = BackgroundTasks()
    asyncio.run(imp.decide(job.import_id, imp.Decision(revision=0, itemRevision=item["choiceRevision"],
                                                     action="retry", index=0), bg, sess))
    asyncio.run(bg())
    assert downloads == ["choice00000"] and job.items[0]["state"] == "ready"


def test_a_slow_library_scan_is_waited_for_instead_of_leaving_the_song_out(lab, monkeypatch):
    """A big batch takes longer to index than the first short wait; the job looks again by itself."""
    sess, songs, playlists, downloads = lab
    job = review_job(sess, 1)
    original_find = imp.navidrome_client.find_song_id
    lookups, pauses = [], []
    async def slow_index(*args, **kwargs):
        lookups.append(1)
        # The song lookup before downloading and the two first index lookups miss.
        return None if len(lookups) <= 3 else await original_find(*args, **kwargs)
    async def pause(seconds):
        pauses.append(seconds)
    monkeypatch.setattr(imp.navidrome_client, "find_song_id", slow_index)
    monkeypatch.setattr(imp, "INDEX_RECHECK_DELAYS_S", (3.0, 6.0, 12.0))
    monkeypatch.setattr(imp.asyncio, "sleep", pause)
    bg = BackgroundTasks()
    asyncio.run(imp.decide(job.import_id, confirm(job, 0), bg, sess))
    asyncio.run(bg())
    item = imp.result(job)["items"][0]
    assert item["state"] == "ready" and item["song_id"], item
    assert item["reason"] is None and item["reviewOrder"] == 0
    assert pauses == [3.0, 6.0], "it stops waiting as soon as the song appears"
    assert downloads == ["choice00000"], "the audio is not downloaded again"
    assert imp.result(job)["status"] == "done"


def test_a_song_the_library_never_shows_still_ends_as_pending_after_the_pauses(lab, monkeypatch):
    sess, songs, playlists, downloads = lab
    job = review_job(sess, 1)
    pauses = []
    async def not_indexed(*args, **kwargs):
        return None
    async def pause(seconds):
        pauses.append(seconds)
    monkeypatch.setattr(imp.navidrome_client, "find_song_id", not_indexed)
    monkeypatch.setattr(imp, "INDEX_RECHECK_DELAYS_S", (3.0, 6.0))
    monkeypatch.setattr(imp.asyncio, "sleep", pause)
    bg = BackgroundTasks()
    asyncio.run(imp.decide(job.import_id, confirm(job, 0), bg, sess))
    asyncio.run(bg())
    item = imp.result(job)["items"][0]
    assert item["state"] == "indexing" and item["reason"] == "index_pending" and item["reviewOrder"] > 0
    assert pauses == [3.0, 6.0] and downloads == ["choice00000"]


def test_global_scan_failure_surfaces_accepted_choice_without_losing_audio(lab, monkeypatch):
    sess, songs, playlists, downloads = lab
    job = review_job(sess, 2)
    async def unavailable(*args):
        raise RuntimeError("fictional indexer unavailable")
    monkeypatch.setattr(imp.navidrome_client, "trigger_scan_and_wait", unavailable)
    bg = BackgroundTasks()
    asyncio.run(imp.decide(job.import_id, confirm(job, 0), bg, sess))
    asyncio.run(bg())
    snapshot = imp.result(job)
    assert snapshot["status"] == "error" and snapshot["error"] == "index_service_unavailable"
    assert snapshot["items"][0]["state"] == "indexing" and snapshot["items"][0]["reviewOrder"] > 0
    assert snapshot["items"][0]["reason"] == "index_pending"
    assert snapshot["items"][1]["reviewOrder"] == 0
    assert downloads == ["choice00000"] and songs
