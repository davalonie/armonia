import copy

import pytest

from routes import import_playlist as imp


def job_with_states(states, **kwargs):
    items = []
    for state, count in states.items():
        for _ in range(count):
            item = imp.new_item({"artist": "Fixture", "title": "Fixture"})
            item["state"] = state
            if state == "ready":
                item["outcome"] = "existing"
            elif state == "indexing":
                item["outcome"] = "downloaded"
            items.append(item)
    return imp.ImportJob("progress-fixture", "Fixture", len(items), items=items, **kwargs)


@pytest.mark.parametrize("indexing,review,processed", [(67, 13, 174), (85, 18, 197), (94, 18, 206)])
def test_large_import_counts_saved_audio_as_processed_not_review(indexing, review, processed):
    job = job_with_states({
        "ready": 94, "indexing": indexing, "review": review, "downloading": 2,
        "pending": 474 - 94 - indexing - review - 2,
    })
    imp.save(job)
    snapshot = imp.result(job)
    assert job.current == snapshot["current"] == processed
    assert job.failed == snapshot["failed"] == snapshot["needsReview"] == review
    assert snapshot["downloaded"] == snapshot["indexing"] == indexing
    assert snapshot["existing"] == snapshot["ready"] == 94
    assert snapshot["errors"] == 0
    assert snapshot["inProgress"] == 2
    assert snapshot["current"] + snapshot["queued"] + snapshot["inProgress"] == 474


def test_legacy_saved_counters_are_corrected_on_read_without_mutating_job():
    job = job_with_states({"ready": 94, "review": 18, "indexing": 94, "downloading": 2, "pending": 266},
                          current=112, failed=112, downloaded=94, existing=94, revision=75, durable=True)
    before = copy.deepcopy(job)
    snapshot = imp.result(job)
    assert snapshot["current"] == 206
    assert snapshot["failed"] == 18
    assert snapshot["indexing"] == 94
    assert snapshot["revision"] == 75
    assert job == before  # Reading does not persist/migrate or increment a revision.


def test_all_item_states_have_distinct_accounting():
    job = job_with_states({
        "ready": 2, "indexing": 3, "review": 4, "not_found": 5, "download_failed": 6,
        "search_failed": 7, "skipped": 8, "source_unavailable": 9,
        "pending": 10, "searching": 11, "downloading": 12,
    })
    snapshot = imp.result(job)
    assert snapshot["current"] == 44
    assert snapshot["needsReview"] == 4
    assert snapshot["errors"] == 18
    assert snapshot["failed"] == 22
    assert snapshot["skipped"] == 8
    assert snapshot["unavailable"] == 9
    assert snapshot["queued"] == 10
    assert snapshot["inProgress"] == 23
    assert snapshot["current"] + snapshot["queued"] + snapshot["inProgress"] == job.total
    assert sum(snapshot[key] for key in ("ready", "indexing", "needsReview", "errors", "skipped", "unavailable")) == snapshot["current"]


def test_finishing_indexing_does_not_double_count_downloads_or_progress():
    job = job_with_states({"indexing": 3})
    imp.save(job)
    before = imp.result(job)
    job.items[0].update(state="ready", song_id="local-fixture")
    imp.save(job)
    after = imp.result(job)
    assert before["current"] == after["current"] == 3
    assert before["downloaded"] == after["downloaded"] == 3
    assert after["ready"] == 1 and after["indexing"] == 2
    assert after["failed"] == 0


@pytest.mark.parametrize("old_phase", ["review", "complete"])
def test_remaining_indexing_is_not_reported_as_complete_or_manual_review(old_phase):
    job = job_with_states({"indexing": 1}, status="done", phase=old_phase, source_info={"source_complete": True})
    snapshot = imp.result(job)
    assert snapshot["phase"] == "indexing_pending"
    assert snapshot["failed"] == snapshot["needsReview"] == 0
    assert snapshot["indexing"] == 1
