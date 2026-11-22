import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal

from fastapi import HTTPException

import db as _db

JobStatus = Literal["pending", "downloading", "tagging", "scanning", "done", "error", "cancelled"]


@dataclass
class Job:
    job_id: str
    video_id: str
    artist: str
    title: str
    username: str = ""
    album: str = ""
    source: str = "youtube_music"
    status: JobStatus = "pending"
    error: str | None = None
    file: str | None = None
    started_at: int = field(default_factory=lambda: int(time.time()))


_jobs: dict[str, Job] = {}
_active_video_ids: set[tuple[str, str]] = set()
_cancelled: set[str] = set()
_lock = Lock()

# Cap on finished jobs retained in memory. The DB holds the full history and the
# status endpoint falls back to it, so evicting old terminal jobs is safe and
# just keeps _jobs/_cancelled from growing without bound over a long uptime.
_MAX_TERMINAL_JOBS = 200
_TERMINAL = ("done", "error", "cancelled")


def _prune_locked() -> None:
    """Drop the oldest terminal jobs beyond the cap. Caller must hold _lock."""
    terminal = [j for j in _jobs.values() if j.status in _TERMINAL]
    excess = len(terminal) - _MAX_TERMINAL_JOBS
    if excess <= 0:
        return
    terminal.sort(key=lambda j: j.started_at)
    for j in terminal[:excess]:
        _jobs.pop(j.job_id, None)
        _cancelled.discard(j.job_id)


def is_video_active(video_id: str, username: str) -> bool:
    with _lock:
        return (username, video_id) in _active_video_ids


def create_job(
    video_id: str, artist: str, title: str, username: str,
    album: str = "", source: str = "youtube_music",
) -> Job:
    job = Job(
        job_id=str(uuid.uuid4()), video_id=video_id, artist=artist, title=title,
        username=username, album=album, source=source,
    )
    with _lock:
        if (username, video_id) in _active_video_ids:
            raise HTTPException(409, "download already in progress for this video")
        if len(_active_video_ids) >= 12 or sum(owner == username for owner, _ in _active_video_ids) >= 5:
            raise HTTPException(429, "download queue is full")
        # Persist before publishing the reservation; a failed DB write cannot
        # leave a phantom job. The duplicate check and insertion are atomic.
        _db.upsert_download(
            job.job_id, video_id, artist, title, "pending",
            username=username, album=album, source=source, started_at=job.started_at,
        )
        _jobs[job.job_id] = job
        _active_video_ids.add((username, video_id))
        _prune_locked()
    return job


def get_job(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def is_cancelled(job_id: str) -> bool:
    return job_id in _cancelled


@contextmanager
def publication_guard(job_id: str):
    """Serialize the final rename with cancellation, never the preceding copy."""
    with _lock:
        yield job_id in _jobs and job_id not in _cancelled


def record_publication(job_id: str, path: str):
    # Called before rename. Keep the intended destination even on cancellation;
    # recovery checks the file itself, not this job's textual status.
    with _lock:
        job = _jobs[job_id]
        _db.upsert_download(job_id, job.video_id, job.artist, job.title, job.status,
                            username=job.username, error=job.error, file_path=path,
                            started_at=job.started_at)
        job.file = path


def cancel_job(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job.status in _TERMINAL:
            return False
        _db.upsert_download(job.job_id, job.video_id, job.artist, job.title, "cancelled",
                            username=job.username, error="Cancelled by user", started_at=job.started_at,
                            completed_at=int(time.time()))
        _cancelled.add(job_id)
        job.status = "cancelled"
        _active_video_ids.discard((job.username, job.video_id))
    return True


def update_job(job_id: str, **fields) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job.status == "cancelled":
            return
        previous = {k: getattr(job, k) for k in fields}
        for k, v in fields.items():
            setattr(job, k, v)
        try:
            completed_at = int(time.time()) if job.status in ("done", "error") else None
            file_size = None
            if job.status == "done" and job.file:
                try:
                    file_size = os.path.getsize(job.file)
                except OSError:
                    pass
            # Keep persistence ordered with cancellation. A late write outside
            # this lock used to overwrite a successfully persisted cancellation.
            _db.upsert_download(
                job.job_id, job.video_id, job.artist, job.title, job.status,
                username=job.username, error=job.error, file_path=job.file, file_size_bytes=file_size,
                started_at=job.started_at, completed_at=completed_at,
            )
        except BaseException:
            for k, v in previous.items():
                setattr(job, k, v)
            raise
        if job.status in _TERMINAL:
            _active_video_ids.discard((job.username, job.video_id))
