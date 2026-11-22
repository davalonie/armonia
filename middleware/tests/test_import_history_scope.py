"""Import history filtering distinguishes processed audio from completed work."""
import copy
import json
from dataclasses import asdict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import db
from auth import get_current_session
from routes import import_playlist as imports


def job(states, *, total=None, **kwargs):
    items = []
    for state in states:
        entry = imports.new_item({"title": "Synthetic", "artist": "Fixture"})
        entry["state"] = state
        items.append(entry)
    return imports.ImportJob("fixture", "Fixture list", len(items) if total is None else total,
                             items=items, status="done", source_info={"source_complete": True}, **kwargs)


def test_474_processed_with_one_indexing_still_has_pending_work():
    current = job(["ready"] * 463 + ["skipped"] * 10 + ["indexing"])
    for item in current.items:
        if item["state"] == "skipped":
            item["manual_pending"] = True
    response = imports.result(current)
    assert response["current"] == response["total"] == 474
    assert response["errors"] == response["needsReview"] == response["legacySkipped"] == 0
    assert response["indexing"] == 1 and response["hasPendingWork"] is True


def test_completed_import_can_include_new_omissions_in_separate_inbox():
    current = job(["ready", "skipped"])
    current.items[1]["manual_pending"] = True
    response = imports.result(current)
    assert response["hasPendingWork"] is False and response["legacySkipped"] == 0
    assert response["ready"] == response["skipped"] == 1


@pytest.mark.parametrize("marker", [None, False, 1, "true"])
def test_legacy_omissions_keep_the_import_visible(marker):
    current = job(["ready", "skipped"])
    if marker is not None:
        current.items[1]["manual_pending"] = marker
    response = imports.result(current)
    assert response["hasPendingWork"] is True and response["legacySkipped"] == 1


@pytest.mark.parametrize("state", ["review", "not_found", "download_failed", "search_failed", "pending",
                                    "searching", "downloading", "source_unavailable", "unknown_future_state"])
def test_unfinished_positions_are_not_completed_history(state):
    response = imports.result(job(["ready", state]))
    assert response["hasPendingWork"] is True


@pytest.mark.parametrize("status", ["running", "paused", "error"])
def test_job_status_is_not_inferred_from_finished_track_counts(status):
    current = job(["ready"])
    current.status = status
    response = imports.result(current)
    assert response["hasPendingWork"] is True
    assert response["resumeAvailable"] is (status == "paused")


@pytest.mark.parametrize("error", ["playlist_missing", "playlist_service_unavailable", "index_service_unavailable"])
def test_playlist_or_service_error_prevents_completed_classification(error):
    current = job(["ready"], error=error)
    assert imports.result(current)["hasPendingWork"] is True


@pytest.mark.parametrize("source_info", [{}, {"source_complete": False}, {"source_complete": None},
                                          {"source_complete": False, "source_total": 300}])
def test_partial_or_unknown_source_cannot_look_complete(source_info):
    current = job(["ready"])
    current.source_info = source_info
    assert imports.result(current)["hasPendingWork"] is True


@pytest.mark.parametrize("total", [0, 2])
def test_missing_or_inconsistent_positions_keep_import_pending(total):
    current = job(["ready"], total=total)
    assert imports.result(current)["hasPendingWork"] is True


def test_extra_unfinished_position_is_not_hidden_by_matching_terminal_count():
    current = job(["ready", "unknown_future_state"], total=1)
    assert imports.result(current)["hasPendingWork"] is True


def test_derived_history_flags_do_not_mutate_job_or_revision():
    current = job(["ready", "skipped"], revision=31)
    before = copy.deepcopy(current)
    first = imports.result(current)
    second = imports.result(current)
    assert first == second and current == before
    assert first["revision"] == 31 and "hasPendingWork" not in asdict(current)


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "armonia.db")
    monkeypatch.setattr(imports, "_imports", {})
    db.init_db()
    sessions = {user: db.get_session(db.create_session(user, "s", "fictional-token", user_id=user))
                for user in ("alice", "bob")}
    selected = [sessions["alice"]]
    app = FastAPI()
    app.include_router(imports.router)
    app.dependency_overrides[get_current_session] = lambda: selected[0]
    return TestClient(app), selected, sessions


def persist(current, ident, owner):
    current.import_id, current.username, current.durable = ident, "nd:" + owner, True
    payload = json.dumps(asdict(current))
    with db._conn() as connection:
        connection.execute("INSERT INTO playlist_imports VALUES(?,?,?,?)", (ident, current.username, payload, 1))
    return payload


def test_history_and_detail_expose_same_flags_only_for_the_owner(api):
    client, selected, sessions = api
    persist(job(["ready"]), "alice-complete", "alice")
    persist(job(["indexing"]), "alice-indexing", "alice")
    persist(job(["review"]), "bob-review", "bob")
    history = client.get("/api/imports").json()["imports"]
    assert {entry["importId"] for entry in history} == {"alice-complete", "alice-indexing"}
    for summary in history:
        detail = client.get("/api/import/" + summary["importId"]).json()
        assert detail["hasPendingWork"] == summary["hasPendingWork"]
        assert detail["legacySkipped"] == summary["legacySkipped"]
        assert "items" not in summary
    assert client.get("/api/import/bob-review").status_code == 404
    selected[0] = sessions["bob"]
    history = client.get("/api/imports").json()["imports"]
    assert len(history) == 1 and history[0]["importId"] == "bob-review" and history[0]["hasPendingWork"]
    assert client.get("/api/import/alice-complete").status_code == 404


def test_restarted_running_job_is_pending_without_persisting_a_read(api):
    client, _, _ = api
    current = job(["ready"], revision=9)
    current.status = "running"
    original = persist(current, "interrupted", "alice")
    summary = client.get("/api/imports").json()["imports"][0]
    detail = client.get("/api/import/interrupted").json()
    assert summary["hasPendingWork"] and summary["resumeAvailable"]
    assert detail["status"] == "error" and detail["phase"] == "interrupted" and detail["revision"] == 9
    with db._conn() as connection:
        persisted = connection.execute("SELECT payload FROM playlist_imports WHERE id='interrupted'").fetchone()[0]
    assert persisted == original
