import asyncio
import json
import logging
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field, fields
from threading import RLock
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from yt_dlp.utils import DownloadError

import db
from auth import get_current_session
from homelab import acoustic_match, import_search, matcher, sources
from homelab.models import Track
from homelab.models import owner as identity_owner
from routes.playlist_edit import playlist_lock
from services import import_metrics, navidrome_client, spotify_client, ytdlp_service
from services.spotify_client import SpotifyError

router = APIRouter()
log = logging.getLogger(__name__)

# How many tracks to download at once during an import. Kept modest: too high
# trips YouTube rate-limiting (403s) and spikes CPU.
IMPORT_CONCURRENCY = 2
# Transient failures (403/timeout/signature blips) often succeed on a second try.
IMPORT_DOWNLOAD_RETRIES = 1
IMPORT_RETRY_BACKOFF_S = 3.0
# A scan of many new files outlasts the short wait after it is triggered. The songs not found
# yet are looked up again after these pauses (45 s in all) before the job gives up on them.
# Without this a large import ended with its downloads saved but left out of the playlist
# until someone pressed «Comprobar biblioteca».
INDEX_RECHECK_DELAYS_S = (3.0, 6.0, 12.0, 24.0)


@dataclass
class ImportJob:
    import_id: str
    name: str
    total: int
    username: str = ""
    status: str = "running"  # running | done | error
    current: int = 0
    downloaded: int = 0
    existing: int = 0
    failed: int = 0
    playlist_id: str | None = None
    error: str | None = None
    failures: list[str] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)
    revision: int = 0
    timings: dict = field(default_factory=dict)
    playlist_base: list[str] = field(default_factory=list)
    create_intent: bool = False
    review_only: bool = False
    cancelled: bool = False
    phase: str = "playlist"
    durable: bool = False
    source_url: str = ""
    source_info: dict = field(default_factory=dict)
    review_accepting: bool = False


_imports: dict[str, ImportJob] = {}
_chained: set = set()  # keeps queued imports' tasks referenced until they end
_lock = RLock()


class ImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    playlistId: str | None = Field(default=None, min_length=1, max_length=128)


class FileImportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    content: str = Field(min_length=1, max_length=4 * 1024**2)
    playlistId: str | None = Field(default=None, min_length=1, max_length=128)


@router.post("/api/import/spotify")
async def import_spotify(
    body: ImportRequest,
    bg: BackgroundTasks,
    sess: dict = Depends(get_current_session),
):
    db.require_active_session(sess)
    library_id = await navidrome_client.require_library_access(sess)
    with _lock:
        if any(j.username == "nd:" + identity_owner(sess) and j.status == "running" for j in _imports.values()):
            raise HTTPException(429, "an import is already running for this user")
    started = time.perf_counter()
    try:
        playlist = await spotify_client.fetch_playlist(body.url)
    except SpotifyError as e:
        log.warning("spotify import rejected (%s)", type(e).__name__)
        raise HTTPException(status_code=400, detail=str(e)) from e
    return await _begin(playlist, body.url, body.playlistId, started, library_id, bg, sess)


@router.post("/api/import/file")
async def import_file(body: FileImportRequest, bg: BackgroundTasks, sess: dict = Depends(get_current_session)):
    """The owner's own export of a playlist: the complete alternative to a partial public view."""
    db.require_active_session(sess)
    library_id = await navidrome_client.require_library_access(sess)
    started = time.perf_counter()
    try:
        playlist = spotify_client.parse_export(body.content, body.name)
    except SpotifyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return await _begin(playlist, "", body.playlistId, started, library_id, bg, sess)


def _same_song(wanted, song):
    """An already imported library song against a source row. Collaborator lists are written
    differently by each source, so the main artist and the exact title identify the position."""
    return matcher.normalized(wanted["title"]) == matcher.normalized(song.get("title", "")) and (
        matcher.normalized(wanted["artist"]) == matcher.normalized(song.get("artist", ""))
        or (matcher.primary(wanted) and matcher.primary(wanted) == matcher.primary(song)))


async def _begin(playlist, source_url, playlist_id, started, library_id, bg, sess):
    job = ImportJob(
        import_id=str(uuid.uuid4()),
        name=playlist["name"],
        total=len(playlist["tracks"]),
        username="nd:" + identity_owner(sess),
    )
    job.durable = True
    job.review_accepting = True
    job.source_url = source_url
    job.source_info = {k: v for k, v in playlist.items() if k not in {"tracks", "name"}}
    job.timings["playlist"] = round(time.perf_counter() - started, 6)
    job.items = [new_item(t) for t in playlist["tracks"]]
    if playlist_id:
        current = await navidrome_client.owned_playlist(playlist_id, sess)
        job.playlist_id = playlist_id
        job.playlist_base = [s["id"] for s in current.get("entry", [])]
        job.review_only = True
        # Legacy imports discarded their progress. Reconstruct an ordered
        # subsequence using the source tags; reject changed/foreign lists.
        cursor = 0
        for song in current.get("entry", []):
            found = None
            for i in range(cursor, len(job.items)):
                if _same_song(job.items[i]["track"], song):
                    found = i
                    break
            if found is None:
                raise HTTPException(409, "playlist no longer matches source order; recovery needs review")
            job.items[found].update(state="ready", song_id=song["id"], outcome="existing")
            cursor = found + 1
    db.require_active_session(sess)
    with _lock:
        if any(j.username == job.username and j.status == "running" for j in _imports.values()):
            raise HTTPException(429, "an import is already running for this user")
        if sum(j.status == "running" for j in _imports.values()) >= 3:
            raise HTTPException(429, "import queue is full")
        if len(_imports) >= 100:
            for key in list(_imports):
                if _imports[key].status != "running":
                    del _imports[key]
                    break
        _imports[job.import_id] = job
        save(job)

    args = (job.import_id, playlist["tracks"], sess["username"], sess["salt"], sess["token"],
            sess.get("library_path"), library_id, sess)
    if bg is None:
        # A queue of playlists (routes.import_batch) starts the next one outside a request.
        task = asyncio.create_task(_run_import(*args))
        _chained.add(task)
        task.add_done_callback(_chained.discard)
    else:
        bg.add_task(_run_import, *args)
    return {"importId": job.import_id, "name": job.name, "total": job.total}


def new_item(track):
    return {
        "track": track,
        "state": "source_unavailable" if track.get("source_unavailable") else "pending",
        "candidates": [],
        "selected": None,
        "song_id": None,
        "outcome": None,
        "timings": {},
        "reason": None,
        "choice_revision": 0,
        "review_order": 0,
    }


# Per-song progress of a running import is written at most once per interval; any other
# save (choices, stage boundaries, the end) is written at once and also carries pending
# progress. A crash loses at most this much progress, never a decision or a publication
# receipt (audio publication has its own journal). Large imports otherwise rewrote megabytes
# several times per song while holding the event loop.
PROGRESS_INTERVAL = 1.0
_written: dict[str, float] = {}
_dirty: set[str] = set()


def save(job, progress=False):
    with _lock:
        _save_locked(job, progress=progress)


def _flush(job):
    with _lock:
        if job.import_id in _dirty:
            _write_locked(job)


def _deferred(job):
    """True when this progress write can wait; schedules the write that will carry it."""
    last = _written.get(job.import_id)
    now = time.monotonic()
    if last is None or now - last >= PROGRESS_INTERVAL:
        return False
    if job.import_id not in _dirty:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        _dirty.add(job.import_id)
        loop.call_later(PROGRESS_INTERVAL - (now - last), _flush, job)
    return True


def _progress(job):
    """Count disjoint processing states; stored audio awaiting Navidrome is not a failure.

    Outcome totals (downloaded/existing) describe how audio was obtained and can
    overlap indexing/ready. Compute on read too: older saved counters excluded
    indexing from current and incorrectly included it in failed.
    """
    counts = Counter(i["state"] for i in job.items)
    errors = sum(counts[s] for s in ("not_found", "download_failed", "search_failed"))
    return {
        "current": sum(counts[s] for s in (
            "ready", "indexing", "review", "not_found", "download_failed", "search_failed",
            "skipped", "source_unavailable",
        )),
        "downloaded": sum(i.get("outcome") == "downloaded" for i in job.items),
        "existing": sum(i.get("outcome") == "existing" for i in job.items),
        # Retain the field for older Android/web clients, without false failures.
        "failed": counts["review"] + errors,
        "needsReview": counts["review"],
        "errors": errors,
        "ready": counts["ready"],
        "indexing": counts["indexing"],
        "queued": counts["pending"],
        "inProgress": counts["searching"] + counts["downloading"],
        "skipped": counts["skipped"],
        "legacySkipped": sum(i["state"] == "skipped" and i.get("manual_pending") is not True for i in job.items),
        "unavailable": counts["source_unavailable"],
    }


def _save_locked(job, omitted_index=None, session=None, progress=False):
    job.revision += 1
    counts = _progress(job)
    for key in ("current", "downloaded", "existing", "failed"):
        setattr(job, key, counts[key])
    job.failures = [
        f"{i['track']['artist']} - {i['track']['title']} — {i['state']}"
        for i in job.items
        if i["state"] in {"review", "not_found", "download_failed", "search_failed"}
    ]
    if job.durable:
        if progress and omitted_index is None and session is None and job.status == "running" and _deferred(job):
            return
        _write_locked(job, omitted_index, session)


def _write_locked(job, omitted_index=None, session=None):
    if job.durable:
        # Shallow copy of the fields: the same JSON as dataclasses.asdict without its deep
        # copy, which cost most of the time of every save on large imports.
        payload = {f.name: getattr(job, f.name) for f in fields(job)}
        # This is a process-local worker gate, not a schema migration. Keeping
        # it out also lets the previous release load durable jobs on rollback.
        payload.pop("review_accepting", None)
        with (db.active_session(session) if session is not None else db._conn()) as c:
            if omitted_index is not None:
                from homelab.manual_inbox import enqueue_omitted
                enqueue_omitted(c, job, omitted_index)
            c.execute(
                "INSERT INTO playlist_imports VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                (job.import_id, job.username, json.dumps(payload), time.time()),
            )
        _written[job.import_id] = time.monotonic()
        _dirty.discard(job.import_id)


def owned(import_id, sess):
    db.require_active_session(sess)
    owner = "nd:" + identity_owner(sess)
    job = _imports.get(import_id)
    if job is None:
        with db._conn() as c:
            row = c.execute(
                "SELECT payload FROM playlist_imports WHERE id=? AND owner=?", (import_id, owner)
            ).fetchone()
        if row:
            job = ImportJob(**json.loads(row["payload"]))
            if job.status == "running":
                job.status = "paused"
                job.phase = "interrupted"
                job.review_accepting = False
            _imports[import_id] = job
    if job is None or job.username != owner:
        raise HTTPException(404, "import not found")
    return job


def result(job):
    with _lock:
        return json.loads(json.dumps(_result(job)))


def _result(job):
    progress = _progress(job)
    has_pending_work = (
        job.status != "done" or bool(job.error)
        or job.source_info.get("source_complete") is not True
        or len(job.items) != job.total
        or progress["ready"] + progress["skipped"] != job.total
        or progress["legacySkipped"] > 0
    )
    phase = job.phase
    if job.status == "done":
        # An older saved phase may say review solely because it was indexing.
        phase = ("review" if progress["failed"] else "indexing_pending" if progress["indexing"]
                 else "source_partial" if not job.source_info.get("source_complete") else "complete")
    return {
        "importId": job.import_id,
        "name": job.name,
        "status": "error" if job.status == "paused" else job.status,
        "resumeAvailable": job.status == "paused",
        "hasPendingWork": has_pending_work,
        "total": job.total,
        "sourceInfo": job.source_info,
        "notRetrieved": max(0,job.source_info.get('source_total',job.total)-job.total) if job.source_info.get('source_total') is not None else None,
        **progress,
        "playlistId": job.playlist_id,
        "error": job.error,
        "failures": job.failures,
        "items": [dict(item, choiceRevision=item.get("choice_revision", 0),
                       manualPending=item.get("manual_pending", False),
                       reviewOrder=item.get("review_order", 0)) for item in job.items],
        "acceptingDecisions": job.status != "running" or (job.review_accepting and not job.cancelled),
        "manualInboxAvailable": True,
        "revision": job.revision,
        "phase": phase,
        "timings": job.timings,
    }


@router.get("/api/imports")
async def list_imports(sess: dict = Depends(get_current_session)):
    db.require_active_session(sess)
    with db._conn() as c:
        rows = c.execute(
            "SELECT id FROM playlist_imports WHERE owner=? ORDER BY updated_at DESC LIMIT 50",
            ("nd:" + identity_owner(sess),),
        ).fetchall()
    return {
        "imports": [
            {k: v for k, v in result(owned(r["id"], sess)).items() if k not in {"items", "failures"}} for r in rows
        ]
    }


@router.get("/api/import/{import_id}")
async def import_status(import_id: str, sess: dict = Depends(get_current_session)):
    return result(owned(import_id, sess))


class DeleteImportRequest(BaseModel):
    revision: int = Field(ge=0)


@router.delete("/api/import/{import_id}")
async def delete_import(import_id: str, body: DeleteImportRequest, sess: dict = Depends(get_current_session)):
    """Forget a stopped import's history only; never remove a playlist or audio."""
    with _lock:
        job = owned(import_id, sess)
        if job.status == "running" or body.revision != job.revision:
            raise HTTPException(409, "import changed or is running; reload before deleting")
        with db._conn() as c:
            c.execute("DELETE FROM playlist_imports WHERE id=? AND owner=?", (import_id, job.username))
        _imports.pop(import_id, None)
    return {"deleted": True}


class Decision(BaseModel):
    revision: int = Field(ge=0)
    action: Literal["confirm", "skip", "retry", "search", "resume", "refresh_source", "create_new"]
    index: int | None = Field(default=None, ge=0)
    source_id: str | None = Field(default=None, max_length=128)
    query: str | None = Field(default=None, min_length=1, max_length=300)
    # refresh_source only: the owner's export, used instead of fetching the public view again.
    content: str | None = Field(default=None, min_length=1, max_length=4 * 1024**2)
    # Item-scoped optimistic concurrency permits choices on other positions
    # while the background worker changes the job's aggregate revision.
    itemRevision: int | None = Field(default=None, ge=0)


def ensure_capacity(job):
    if any(j.status == "running" and j.username == job.username and j is not job for j in _imports.values()):
        raise HTTPException(429, "an import is already running for this user")
    if sum(j.status == "running" for j in _imports.values()) >= 3:
        raise HTTPException(429, "import queue is full")


def start_worker(job, sess, bg):
    ensure_capacity(job)
    job.status = "running"
    job.cancelled = False
    job.review_accepting = True
    job.error = None
    save(job)
    args = (job.import_id, [i["track"] for i in job.items], sess["username"], sess["salt"], sess["token"],
            sess.get("library_path"), sess.get("library_id"), sess)
    if bg is None:
        task = asyncio.create_task(_run_import(*args))
        _chained.add(task)
        task.add_done_callback(_chained.discard)
    else:
        bg.add_task(_run_import, *args)


@router.post("/api/import/{import_id}/decision")
async def decide(import_id: str, body: Decision, bg: BackgroundTasks, sess: dict = Depends(get_current_session)):
    job = owned(import_id, sess)
    was_running = job.status == "running"
    # No await between validation and durable reservation. Old clients retain
    # the job-level contract; new clients compare only the affected position.
    item_action = body.action in {"confirm", "skip", "retry", "search"}
    if item_action and body.itemRevision is not None:
        if body.index is None or body.index >= len(job.items):
            raise HTTPException(400, "invalid track position")
        item = job.items[body.index]
        if body.itemRevision != item.get("choice_revision", 0):
            raise HTTPException(409, "track choice changed; reload before choosing")
        if was_running and (not job.review_accepting or job.cancelled or item["state"] not in {
            "review", "not_found", "search_failed", "download_failed", "source_unavailable", "skipped",
        }):
            raise HTTPException(409, "track is being processed; reload before choosing")
    elif body.revision != job.revision or was_running:
        raise HTTPException(409, "import changed; reload before choosing")
    if not was_running and body.action != "skip":
        ensure_capacity(job)
    if body.action == "create_new":
        if not job.playlist_id or job.error != "playlist_missing":
            raise HTTPException(409, "only a missing destination can be recreated")
        job.cancelled = False
        job.status = "running"  # Reserve the job during the remote recheck.
        save(job)
        try:
            try:
                await navidrome_client.owned_playlist(job.playlist_id, sess)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
            else:
                raise HTTPException(409, "destination exists; reload before recovering")
            db.require_active_session(sess)
            if job.cancelled:
                raise HTTPException(409, "import paused")
            # Explicit user recovery only. Ready positions and manual choices
            # survive; the worker reuses them without downloading their audio.
            job.playlist_id = None
            job.playlist_base = []
            job.create_intent = False
        finally:
            job.status = "paused"
            save(job)
        start_worker(job, sess, bg)
        return result(job)
    if body.action == "refresh_source":
        job.cancelled = False
        job.status = "running"  # reserve across network awaits
        save(job)
        try:
            if body.content:
                try:
                    playlist = spotify_client.parse_export(body.content, job.name)
                except SpotifyError as e:
                    # Not a rereadable link (an archive or sign-in import): explain, never a 500.
                    raise HTTPException(400, str(e)) from e
            elif job.source_info.get("metadata_source") == "file":
                raise HTTPException(409, "este trabajo se importó desde un archivo; vuelve a aportarlo para completarlo")
            else:
                try:
                    playlist = await spotify_client.fetch_playlist(job.source_url)
                except SpotifyError as e:
                    # Not a rereadable link (an archive or sign-in import): explain, never a 500.
                    raise HTTPException(400, str(e)) from e
            db.require_active_session(sess)
            if job.cancelled:
                raise HTTPException(409, "import paused")
            fresh = playlist['tracks']
            if len(fresh) < len(job.items):
                raise HTTPException(409, "source returned fewer positions; original playlist preserved")
            for old, new in zip(job.items, fresh, strict=False):
                previous = old['track']
                if previous.get('source_unavailable'):
                    if previous.get('source_id') and new.get('source_id') and previous['source_id'] != new['source_id']:
                        raise HTTPException(409, "source position changed; original playlist preserved")
                    continue
                if body.content:
                    # Another source of the same list: identifiers when both carry them, else title and main artist.
                    same = (previous['source_id'] == new['source_id'] if previous.get('source_id') and new.get('source_id')
                            else _same_song(previous, new))
                    if not same:
                        raise HTTPException(409, "el archivo no corresponde a esta importación; playlist conservada")
                    continue
                if any(previous.get(k) != new.get(k) for k in ('title', 'artist', 'duration')) or (
                    previous.get('source_id') and previous.get('source_id') != new.get('source_id')
                ):
                    raise HTTPException(409, "source order changed; original playlist preserved")
            for i, old in enumerate(job.items):
                if old['track'].get('source_unavailable') and not fresh[i].get('source_unavailable'):
                    if old['state'] == 'source_unavailable':
                        job.items[i] = new_item(fresh[i])
                    else:
                        old['track'] = fresh[i]  # A manual decision still owns this position.
            job.items.extend(new_item(t) for t in fresh[len(job.items):])
            job.total = len(job.items)
            job.source_info = {k: v for k, v in playlist.items() if k not in {'tracks', 'name'}}
        finally:
            job.status = "paused"
            save(job)
        start_worker(job, sess, bg)
        return result(job)
    if body.action == "resume":
        # Songs left for review by an earlier matcher are judged again from their stored
        # candidates (no new search). A manual decision is never replaced.
        for item in job.items:
            if item["state"] != "review" or item.get("decision") or item.get("selected") or not item.get("candidates"):
                continue
            try:
                stored = [Track(**c["track"]) for c in item["candidates"]]
                ranked = matcher.rank(item["track"], stored)
                item["candidates"] = ranked["candidates"]
                item["comparison_reason"] = ranked.get("choiceReason")
                item["choice_revision"] = item.get("choice_revision", 0) + 1
                chosen = ranked["selected"]
                if chosen:
                    sources.allowed(chosen["source"], chosen["source_id"], "persist")
                    item.update(selected=chosen, state="pending", reason=None, outcome=item.get("outcome"))
            except (ValidationError, HTTPException):
                continue
    if body.action != "resume":
        if body.index is None or body.index >= len(job.items):
            raise HTTPException(400, "invalid track position")
        item = job.items[body.index]
        if item["state"] == "ready":
            raise HTTPException(409, "track is already in the playlist")
        if body.action == "confirm":
            chosen = next((c["track"] for c in item["candidates"] if c["track"]["source_id"] == body.source_id), None)
            if not chosen:
                raise HTTPException(400, "choose a current candidate")
            sources.allowed(chosen["source"], chosen["source_id"], "persist")
            previous = item.get("selected") or {}
            if (previous.get("source"), previous.get("source_id")) != (chosen["source"], chosen["source_id"]):
                # A publication belongs to its recording, not to the source row.
                # Keep the old file in the library, but do not treat a different
                # choice as already downloaded and wait forever for its index.
                item.update(outcome=None, song_id=None)
            item.update(selected=chosen, state="pending", decision="confirmed", reason=None)
        elif body.action == "skip":
            previous_item = dict(item)
            previous_progress = {key: getattr(job, key) for key in (
                "revision", "current", "downloaded", "existing", "failed", "failures")}
            with _lock:
                try:
                    item.update(state="skipped", decision="skipped", review_order=0, manual_pending=True,
                                choice_revision=item.get("choice_revision", 0) + 1)
                    # Omission and its inbox reference commit together. If the
                    # database rejects either, the visible choice stays intact.
                    _save_locked(job, omitted_index=body.index, session=sess)
                except Exception:
                    item.clear()
                    item.update(previous_item)
                    for key, value in previous_progress.items():
                        setattr(job, key, value)
                    raise
            return result(job)
        elif body.action == "search":
            item.update(
                query=body.query or f"{item['track']['artist']} {item['track']['title']}",
                selected=None,
                outcome=None,
                song_id=None,
                decision=None,
                reason=None,
                state="pending",
                manual_search=True,
            )
        elif body.action == "retry":
            item.update(state="pending")
        item["choice_revision"] = item.get("choice_revision", 0) + 1
        item["review_order"] = 0
    if was_running:
        # The existing worker drains newly accepted positions before stopping.
        # No second worker, scan or playlist writer is started by this request.
        save(job)
        return result(job)
    start_worker(job, sess, bg)
    return result(job)


@router.post("/api/import/{import_id}/cancel")
async def cancel(import_id: str, sess: dict = Depends(get_current_session)):
    job = owned(import_id, sess)
    with _lock:
        job.cancelled = True
        job.review_accepting = False
    if job.status != "running":
        job.status = "paused"
    save(job)
    return result(job)


def _resolve_music_dir(library_path: str | None) -> str | None:
    return library_path


async def _download_with_retry(
    video_id: str, artist: str, title: str, music_dir: str | None, sess: dict, album: str = "Singles",
    artists=None, album_artist: str | None = None, details=None,
) -> str:
    """Download a track, retrying once (with backoff) on transient failures."""

    async def authorize():
        if sess.get("import_cancel_check", lambda: False)():
            raise ytdlp_service.DownloadCancelled("import paused")
        sources.allowed("youtube", video_id, "persist")
        return await navidrome_client.require_library_access(sess)

    @contextmanager
    def final_guard():
        with _lock, db.active_session(sess):
            if sess.get("import_cancel_check", lambda: False)():
                raise ytdlp_service.DownloadCancelled("import paused")
            yield

    for attempt in range(IMPORT_DOWNLOAD_RETRIES + 1):
        try:
            return await ytdlp_service.download_limited(
                video_id,
                artist,
                title,
                "youtube_music",
                music_dir=music_dir,
                album=album,
                authorize=authorize,
                final_guard=final_guard,
                cancel_check=sess.get("import_cancel_check"),
                artists=artists,
                album_artist=album_artist,
                details=details,
            )
        except DownloadError as e:
            if attempt >= IMPORT_DOWNLOAD_RETRIES or not ytdlp_service.is_retryable(e):
                raise
            log.info(
                "import: retry %d/%d for %s - %s (%s)",
                attempt + 1,
                IMPORT_DOWNLOAD_RETRIES,
                artist,
                title,
                ytdlp_service.describe_error(e),
            )
            with import_metrics.measure("retry_backoff"):
                await asyncio.sleep(IMPORT_RETRY_BACKOFF_S)
    raise RuntimeError("unreachable")  # loop either returns or raises


@contextmanager
def stage(job, item, name):
    job.phase = name
    if item is not None:
        item["stage"] = name
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        job.timings[name] = round(job.timings.get(name, 0) + elapsed, 6)
        if item is not None:
            item["timings"][name] = round(item["timings"].get(name, 0) + elapsed, 6)


async def _run_import(import_id, tracks, username, salt, token, library_path, library_id, session):
    job = _imports[import_id]
    job.review_accepting = not job.cancelled
    if not job.items:
        job.items = [new_item(t) for t in tracks]
    sess = {
        **session,
        "username": username,
        "salt": salt,
        "token": token,
        "library_path": library_path,
        "library_id": library_id,
        "import_cancel_check": lambda: job.cancelled,
    }
    sem = asyncio.Semaphore(IMPORT_CONCURRENCY)

    def active():
        db.require_active_session(sess)
        if job.cancelled:
            raise ytdlp_service.DownloadCancelled("import paused")

    async def handle(item):
        if item["state"] in {"ready", "review", "not_found", "search_failed", "download_failed", "skipped", "source_unavailable"}:
            return
        async with sem:
            track = item["selected"] if item.get("decision") == "confirmed" and item.get("selected") else item["track"]
            artist, title = track["artist"], track["title"]

            def metric(name, seconds):
                with _lock:
                    item["stage"] = name
                    item["timings"][name] = round(item["timings"].get(name, 0) + seconds, 6)
                    job.timings[name] = round(job.timings.get(name, 0) + seconds, 6)

            metric_token = import_metrics.sink.set(metric)
            try:
                active()
                with stage(job, item, "library_lookup"):
                    existing = await navidrome_client.find_song_id(artist, title, username, salt, token, track)
                active()
                if existing:
                    item.update(state="ready", song_id=existing, outcome=item.get("outcome") or "existing")
                    return
                if item.get("outcome") == "downloaded":
                    item["state"] = "indexing"
                    return  # published already; index again, never redownload
                if not item.get("selected"):
                    item["state"] = "searching"
                    with stage(job, item, "search"):
                        ranked = await import_search.resolve(track, active, item.get('query'))
                    active()
                    item['search_attempts'] = ranked['attempts']
                    item['provider_errors'] = ranked['provider_errors']
                    item["candidates"] = ranked["candidates"]
                    item["comparison_reason"] = ranked.get("choiceReason")
                    item["choice_revision"] = item.get("choice_revision", 0) + 1
                    manual = item.pop("manual_search", False)
                    item["selected"] = ranked["selected"] if not manual else None
                    if not item['selected'] and not manual:
                        with stage(job, item, 'acoustic'):
                            item['acoustic'] = await acoustic_match.resolve(track, ranked['candidates'],
                                                                           identity_owner(sess) if sess.get("user_id") else job.username, active)
                        item['selected'] = item['acoustic'].get('selected')
                    if not item["selected"]:
                        item["state"] = "review" if ranked['candidates'] else (
                            "search_failed" if ranked['provider_errors'] else "not_found")
                        item['reason'] = 'ambiguous' if ranked['candidates'] else ('provider_unavailable' if ranked['provider_errors'] else 'not_found')
                        return
                active()
                selected = item["selected"]
                sources.allowed("youtube", selected["source_id"], "persist")
                item["state"] = "downloading"
                save(job)  # durable selected recording before any audio publication

                with stage(job, item, "audio_total"):
                    await _download_with_retry(
                        selected["source_id"], artist, title, library_path, sess, track.get("album") or "Singles",
                        artists=track.get("artists"), album_artist=track.get("album_artist"),
                        details=track.get("details"),
                    )
                item.update(state="indexing", outcome="downloaded")
            except ytdlp_service.DownloadCancelled:
                job.cancelled = True
            except HTTPException as exc:
                if exc.status_code in (401, 403):
                    job.cancelled = True
                if exc.status_code == 409 and "recording already saved" in str(exc.detail):
                    item.update(state="indexing", outcome="downloaded")
                    return
                item["state"] = "download_failed"
                item["reason"] = "permission" if exc.status_code in (401, 403) else "service_unavailable"
            except Exception:
                item["state"] = "search_failed" if item["state"] == "searching" else "download_failed"
                item["reason"] = "provider_unavailable"
                log.warning("import %s: stage unavailable", import_id)
            finally:
                if item["state"] in {"download_failed", "search_failed", "not_found", "review"} and item.get("decision") == "confirmed":
                    item["review_order"] = job.revision + 1
                import_metrics.sink.reset(metric_token)
                save(job, progress=True)

    started = time.perf_counter()
    try:
        async with navidrome_client.connection_scope():
            # A crash may have happened after publication but before checkpoint.
            # Scan before looking up interrupted downloads; the publication journal
            # still prevents a second write if indexing remains unavailable.
            if any(i["state"] in {"downloading", "indexing"} for i in job.items):
                active()
                with stage(job, None, "indexing"):
                    await navidrome_client.trigger_scan_and_wait(username, salt, token)
            while True:
                with ytdlp_service.search_connection_scope():
                    await asyncio.gather(*(handle(item) for item in job.items))
                active()
                waiting = [i for i in job.items if i["state"] == "indexing"]
                if waiting:
                    with stage(job, None, "indexing"):
                        await navidrome_client.trigger_scan_and_wait(username, salt, token)
                        async def finish_index(item):
                            async with sem:
                                active()
                                recording = (item["selected"] if item.get("decision") == "confirmed"
                                             and item.get("selected") else item["track"])
                                sid = await navidrome_client.find_song_id(
                                    recording["artist"], recording["title"], username, salt, token, recording)
                                active()
                                if sid:
                                    if item.get("reason") == "index_pending":
                                        item.update(reason=None, review_order=0)
                                    item.update(state="ready", song_id=sid)
                                else:
                                    item["reason"] = "index_pending"
                                    if item.get("decision") == "confirmed":
                                        item["review_order"] = job.revision + 1
                                save(job, progress=True)
                        await asyncio.gather(*(finish_index(item) for item in waiting))
                        for delay in INDEX_RECHECK_DELAYS_S:
                            waiting = [i for i in waiting if i["state"] == "indexing"]
                            if not waiting:
                                break
                            await asyncio.sleep(delay)
                            active()
                            await navidrome_client.trigger_scan_and_wait(username, salt, token)
                            await asyncio.gather(*(finish_index(item) for item in waiting))
                ids = [i["song_id"] for i in job.items if i["song_id"]]
                active()
                if ids:
                    with stage(job, None, "playlist_update"):
                        if job.playlist_id:
                            async with playlist_lock(job.playlist_id):
                                current = await navidrome_client.owned_playlist(job.playlist_id, sess)
                                current_ids = [s["id"] for s in current.get("entry", [])]
                                if current_ids != ids:
                                    if current_ids != job.playlist_base:
                                        raise HTTPException(409, "playlist changed outside import; recovery needs review")
                                    await navidrome_client.import_playlist_request(
                                        "createPlaylist",
                                        sess,
                                        [("playlistId", job.playlist_id)] + [("songId", s) for s in ids],
                                    )
                                job.playlist_base = ids
                                save(job)
                        elif job.create_intent:
                            raise HTTPException(409, "playlist creation uncertain; attach the existing playlist to recover")
                        else:
                            job.create_intent = True
                            save(job)
                            job.playlist_id = await navidrome_client.create_playlist(job.name, ids, username, salt, token)
                            if not job.playlist_id:
                                raise HTTPException(502, "playlist creation uncertain; check playlists before retrying")
                            job.playlist_base = ids
                            save(job)
                if any(i["state"] == "pending" for i in job.items):
                    continue
                job.status = "done"
                job.phase = "review" if job.failed else ("source_partial" if not job.source_info.get("source_complete") else "complete")
                break
    except ytdlp_service.DownloadCancelled:
        job.status = "paused"
        job.phase = "paused"
    except Exception as exc:
        failed_phase = job.phase
        job.status = "paused"
        job.phase = "recovery"
        if isinstance(exc, HTTPException) and exc.status_code == 409:
            job.error = exc.detail
        elif isinstance(exc, HTTPException) and exc.status_code in (401, 403):
            job.error = "session_expired" if exc.status_code == 401 else "permission_denied"
        elif isinstance(exc, HTTPException) and exc.status_code == 404 and failed_phase == "playlist_update":
            job.error = "playlist_missing"
        elif failed_phase == "playlist_update":
            job.error = "playlist_service_unavailable"
        elif failed_phase == "indexing":
            job.error = "index_service_unavailable"
        else:
            job.error = "service_unavailable"
        # Exception strings may contain upstream URLs with authentication.
        log.warning("import %s: %s failed (%s)", import_id, failed_phase, type(exc).__name__)
    finally:
        job.review_accepting = False
        if job.status == "paused" and job.error:
            # Accepted choices can be left queued when a batch-level scan or
            # publication fails. Surface them after untouched review questions.
            for offset, item in enumerate(job.items):
                if item.get("decision") == "confirmed" and item["state"] in {"pending", "searching", "downloading", "indexing"}:
                    item["review_order"] = item.get("review_order") or job.revision + offset + 1
                    item["reason"] = "index_pending" if item["state"] == "indexing" else "service_unavailable"
        job.timings["wall"] = round(job.timings.get("wall", 0) + time.perf_counter() - started, 6)
        save(job)
        # Still "running" here means the worker itself was cancelled (server stopping): the
        # queue must not start another playlist now; «Continuar» resumes this one later.
        if job.source_info.get("batch_id") and job.status != "running":
            from routes import import_batch
            await import_batch.finished(job, session)


class AttachRequest(BaseModel):
    revision: int = Field(ge=0)
    playlistId: str = Field(min_length=1, max_length=128)


@router.post("/api/import/{import_id}/attach")
async def attach_existing(import_id: str, body: AttachRequest, sess: dict = Depends(get_current_session)):
    """Recover a lost create response without losing saved manual choices."""
    job = owned(import_id, sess)
    if job.status == "running" or body.revision != job.revision:
        raise HTTPException(409, "import changed; reload before attaching")
    job.status = "running"  # reserve across the remote ownership/read check
    save(job)
    try:
        playlist = await navidrome_client.owned_playlist(body.playlistId, sess)
        ids = [i["song_id"] for i in job.items if i["song_id"]]
        if [s["id"] for s in playlist.get("entry", [])] != ids:
            raise HTTPException(409, "existing playlist differs from imported songs")
        job.playlist_id = body.playlistId
        job.playlist_base = ids
        job.error = None
        job.phase = "review" if job.failed else ("source_partial" if not job.source_info.get("source_complete") else "complete")
    finally:
        job.status = "done" if job.error is None and job.playlist_id else "paused"
        save(job)
    return result(job)
