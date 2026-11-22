import asyncio
import json

import pytest
from fastapi import BackgroundTasks, HTTPException
from test_import_choice_queue import review_job
from test_import_review import lab as lab

import db
from homelab import manual_inbox
from routes import import_playlist as imp


def omit(job, sess):
    return asyncio.run(imp.decide(job.import_id, imp.Decision(revision=job.revision,
        itemRevision=job.items[0].get("choice_revision", 0), action="skip", index=0), BackgroundTasks(), sess))


def test_omitted_reference_survives_deleting_import_history_and_is_private(lab):
    sess, songs, playlists, downloads = lab
    job = review_job(sess, 1)
    result = omit(job, sess)
    assert result["manualInboxAvailable"] and result["items"][0]["state"] == "skipped"
    assert result["items"][0]["manualPending"] is True
    stored = manual_inbox.list_items(sess)
    assert len(stored) == 1 and stored[0]["originIndex"] == 0
    assert stored[0]["track"]["title"] == "Song 0" and stored[0]["status"] == "pending"
    omit(job, sess)  # Explicit repeated omission does not duplicate the reference.
    assert len(manual_inbox.list_items(sess)) == 1
    asyncio.run(imp.delete_import(job.import_id, imp.DeleteImportRequest(revision=job.revision), sess))
    assert len(manual_inbox.list_items(sess)) == 1
    bob = db.get_session(db.create_session("bob", "salt", "token", user_id="bob-id"))
    assert not manual_inbox.list_items(bob)
    with pytest.raises(HTTPException) as error:
        manual_inbox.owned(stored[0]["id"], bob)
    assert error.value.status_code == 404
    assert not songs and not playlists and not downloads


def test_historical_omissions_are_not_silently_hidden_or_migrated(lab):
    sess, *_ = lab
    job = review_job(sess, 1)
    job.items[0]["state"] = "skipped"
    imp.save(job)
    result = imp.result(job)
    assert result["manualInboxAvailable"] is True
    assert result["items"][0]["manualPending"] is False
    assert not manual_inbox.list_items(sess)


def test_omission_and_reference_rollback_together_if_database_fails(lab, monkeypatch):
    sess, *_ = lab
    job = review_job(sess, 1)
    before = imp.result(job)
    enqueue = manual_inbox.enqueue_omitted

    def broken(connection, *args):
        enqueue(connection, *args)
        raise HTTPException(503, "fictional write failure")

    monkeypatch.setattr(manual_inbox, "enqueue_omitted", broken)
    with pytest.raises(HTTPException) as error:
        omit(job, sess)
    assert error.value.status_code == 503
    assert imp.result(job) == before
    assert not manual_inbox.list_items(sess)
    imp._imports.clear()
    assert imp.owned(job.import_id, sess).items[0]["state"] == "review"


def test_accept_omission_while_another_song_runs_without_new_worker(lab):
    sess, *_ = lab
    job = review_job(sess, 2)
    job.status = "running"
    job.review_accepting = True
    job.items[1]["state"] = "downloading"
    result = omit(job, sess)
    assert result["status"] == "running" and result["items"][1]["state"] == "downloading"
    assert len(manual_inbox.list_items(sess)) == 1


def test_session_revoked_between_initial_check_and_commit_cannot_omit(lab, monkeypatch):
    sess, *_ = lab
    job = review_job(sess, 1)
    before = imp.result(job)
    original_save = imp._save_locked

    def revoke_then_save(job, **kwargs):
        db.delete_session(sess["id"])
        return original_save(job, **kwargs)

    monkeypatch.setattr(imp, "_save_locked", revoke_then_save)
    with pytest.raises(HTTPException) as error:
        omit(job, sess)
    assert error.value.status_code == 401
    assert imp.result(job) == before
    with db._conn() as connection:
        assert connection.execute("SELECT COUNT(*) FROM manual_inbox").fetchone()[0] == 0
        saved = connection.execute("SELECT payload FROM playlist_imports WHERE id=?", (job.import_id,)).fetchone()[0]
    assert json.loads(saved)["items"][0]["state"] == "review"
