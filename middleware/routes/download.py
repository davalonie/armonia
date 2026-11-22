import logging
import re
import unicodedata
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from yt_dlp.utils import DownloadError

import db as _db
from auth import get_current_session
from homelab import sources
from homelab.models import owner as identity_owner
from jobs import (
    cancel_job,
    create_job,
    get_job,
    is_cancelled,
    is_video_active,
    publication_guard,
    record_publication,
    update_job,
)
from services import navidrome_client, safe_files, ytdlp_service
from services.ytdlp_service import DownloadCancelled


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


async def _is_duplicate(artist: str, title: str, username: str, salt: str, token: str) -> bool:
    songs = await navidrome_client.search_songs(title, username, salt, token)
    na, nt = _norm(artist), _norm(title)
    return any(_norm(s.get("title", "")) == nt and _norm(s.get("artist", "")) == na for s in songs)

router = APIRouter()
log = logging.getLogger(__name__)


def _can_access(owner: str | None, sess: dict) -> bool:
    """Downloads are private even when another application user is an admin."""
    return owner == "nd:" + identity_owner(sess)


class DownloadRequest(BaseModel):
    videoId: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    artist: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=256)
    source: str = Field(default="youtube_music", pattern="^(youtube|youtube_music)$")
    album: str = Field(default="")
    force: bool = Field(default=False)


@router.post("/api/download")
async def download(
    body: DownloadRequest,
    bg: BackgroundTasks,
    sess: dict = Depends(get_current_session),
):
    _db.require_active_session(sess)
    library_id = await navidrome_client.require_library_access(sess)
    sources.allowed("youtube", body.videoId, "persist")
    if is_video_active(body.videoId, "nd:" + identity_owner(sess)):
        raise HTTPException(
            status_code=409, detail="download already in progress for this video"
        )
    if not body.force and await _is_duplicate(
        body.artist, body.title, sess["username"], sess["salt"], sess["token"]
    ):
        raise HTTPException(status_code=409, detail="already in library")
    job = create_job(body.videoId, body.artist, body.title, "nd:" + identity_owner(sess), body.album, body.source)
    bg.add_task(
        _run_download,
        job.job_id,
        body.videoId,
        body.artist,
        body.title,
        sess["username"],
        sess["salt"],
        sess["token"],
        sess.get("library_path"),
        body.source,
        body.album,
        library_id,
        sess,
        body.force,
    )
    return {"jobId": job.job_id, "status": job.status}


async def _run_download(
    job_id: str,
    video_id: str,
    artist: str,
    title: str,
    username: str,
    salt: str,
    token: str,
    library_path: str | None = None,
    source: str = "youtube_music",
    album: str = "",
    library_id: int | None = None,
    session: dict | None = None,
    allow_repeat: bool = False,
) -> None:
    @contextmanager
    def final_guard():
        with publication_guard(job_id) as allowed:
            if not allowed:
                raise DownloadCancelled("cancelled by user")
            with _db.active_session(session or {}):
                yield

    async def authorize():
        sources.allowed("youtube", video_id, "persist")
        return await navidrome_client.require_library_access({
            **(session or {}), "username": username, "salt": salt, "token": token,
            "library_path": library_path, "library_id": library_id,
        })
    try:
        _db.require_active_session(session or {})
        music_dir = library_path
        update_job(job_id, status="downloading")
        file_path = await ytdlp_service.download_limited(
            video_id, artist, title, source,
            cancel_check=lambda: is_cancelled(job_id),
            music_dir=music_dir, album=album,
            final_guard=final_guard,
            record_intent=lambda path: record_publication(job_id, path),
            allow_repeat=allow_repeat,
            authorize=authorize,
        )

        if is_cancelled(job_id):
            return

        update_job(job_id, status="tagging", file=file_path)
        # Songs already matching these tags (a forced re-download), so the wait
        # below only succeeds once the *new* file is indexed.
        try:
            known_ids = await navidrome_client.matching_song_ids(artist, title, username, salt, token)
        except Exception:
            known_ids = set()

        if is_cancelled(job_id):
            return

        update_job(job_id, status="scanning")
        # Rescan just the folder we wrote to, and only report "done" once the
        # song is actually searchable — so the client's refresh finds it.
        targets = None
        if music_dir and library_id is not None:
            t = navidrome_client.scan_target(library_id, music_dir, Path(file_path).parent)
            targets = [t] if t else None
        await navidrome_client.scan_until(
            username, salt, token,
            done=lambda: navidrome_client.new_song_visible(artist, title, known_ids, username, salt, token),
            targets=targets,
        )

        update_job(job_id, status="done")
    except DownloadCancelled:
        pass  # cancel_job already set status; nothing more to do
    except DownloadError as e:
        reason = ytdlp_service.describe_error(e)
        log.warning("download job %s failed: %s", job_id, reason)
        update_job(job_id, status="error", error=reason)
    except Exception as e:
        # Unexpected (our bug, Navidrome, network) — keep the traceback.
        log.warning("download job %s failed (%s)", job_id, type(e).__name__)
        update_job(job_id, status="error", error="download unavailable")


@router.get("/api/status/{job_id}")
async def status(job_id: str, sess: dict = Depends(get_current_session)):
    job = get_job(job_id)
    if job is not None:
        if not _can_access(job.username, sess):
            raise HTTPException(status_code=404, detail="job not found")
        return {
            "jobId": job.job_id,
            "status": job.status,
            "error": job.error,
            "file": job.file,
        }
    # In-memory job is gone (e.g. process restarted). Fall back to the persisted
    # record so the client sees the final status instead of a spurious 404.
    rec = _db.get_download_record(job_id)
    if rec is None or not _can_access(rec["username"], sess):
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "jobId": rec["id"],
        "status": rec["status"],
        "error": rec["error"],
        "file": rec["file_path"],
    }


@router.post("/api/rescan")
async def rescan(sess: dict = Depends(get_current_session)):
    await navidrome_client.trigger_scan_and_wait(sess["username"], sess["salt"], sess["token"])
    return {"ok": True}


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job_endpoint(job_id: str, sess: dict = Depends(get_current_session)):
    job = get_job(job_id)
    if job is None or not _can_access(job.username, sess):
        raise HTTPException(status_code=404, detail="job not found or already finished")
    if not cancel_job(job_id):
        raise HTTPException(status_code=404, detail="job not found or already finished")
    return {"ok": True}


@router.get("/api/downloads")
def list_downloads(sess: dict = Depends(get_current_session)):
    return {"downloads": _db.list_downloads("nd:" + identity_owner(sess))}


@router.delete("/api/downloads/{job_id}")
def delete_download(job_id: str, sess: dict = Depends(get_current_session)):
    rec = _db.get_download_record(job_id)
    if rec is None or not _can_access(rec["username"], sess):
        raise HTTPException(status_code=404, detail="download not found")
    _db.delete_download_record(job_id)
    return {"ok": True}


@router.post("/api/downloads/{job_id}/retry")
async def retry_download(
    job_id: str,
    bg: BackgroundTasks,
    sess: dict = Depends(get_current_session),
):
    _db.require_active_session(sess)
    library_id = await navidrome_client.require_library_access(sess)
    rec = _db.get_download_record(job_id)
    if rec is None or not _can_access(rec["username"], sess):
        raise HTTPException(status_code=404, detail="download not found")
    sources.allowed("youtube", rec["video_id"], "persist")
    if is_video_active(rec["video_id"], "nd:" + identity_owner(sess)):
        raise HTTPException(status_code=409, detail="download already in progress for this video")
    # A restart can interrupt indexing after the file was already published.
    # Retrying that job must not silently create a second permanent recording.
    if rec.get("file_path"):
        try:
            exists = safe_files.private_file_exists(safe_files.library_root(sess["library_path"]), rec["file_path"])
        except (ValueError, OSError) as exc:
            raise HTTPException(409, "saved file cannot be verified in your library") from exc
        if exists:
            raise HTTPException(409, "recording already saved; rescan your library")
    if await _is_duplicate(rec["artist"], rec["title"], sess["username"], sess["salt"], sess["token"]):
        raise HTTPException(409, "already in library")

    source = rec.get("source") or "youtube_music"
    album = rec.get("album") or ""
    # Re-run as a fresh job owned by the caller (it uses their credentials and
    # library), then drop the old record so the list shows a single entry
    # that's downloading again.
    job = create_job(rec["video_id"], rec["artist"], rec["title"], "nd:" + identity_owner(sess), album, source)
    _db.delete_download_record(job_id)
    bg.add_task(
        _run_download,
        job.job_id,
        rec["video_id"],
        rec["artist"],
        rec["title"],
        sess["username"],
        sess["salt"],
        sess["token"],
        sess.get("library_path"),
        source,
        album,
        library_id,
        sess,
    )
    return {"jobId": job.job_id, "status": job.status}
