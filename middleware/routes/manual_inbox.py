"""Receive an owner's MP3 for a deferred reference, without changing playlists."""
import asyncio
import errno
import os
import shutil
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from mutagen.id3 import COMM, ID3
from pydantic import BaseModel, Field
from starlette.requests import ClientDisconnect

import db
from auth import get_current_session
from homelab import manual_inbox as inbox
from homelab import operations, publications, store
from homelab.matcher import normalized
from services import navidrome_client as nd
from services import safe_files, tagger_service
from services.ytdlp_service import _sanitize

router = APIRouter(prefix="/api/manual-inbox", tags=["manual music imports"])
MAX_UPLOAD = 64 * 1024**2
MAX_OUTPUT = 96 * 1024**2
_slots = asyncio.Semaphore(2)


@asynccontextmanager
async def _upload_slot():
    try:
        await asyncio.wait_for(_slots.acquire(), timeout=1)
    except TimeoutError as exc:
        raise HTTPException(429, "two MP3 uploads are already being processed", headers={"Retry-After": "5"}) from exc
    try:
        yield
    finally:
        _slots.release()


class Revision(BaseModel):
    revision: int = Field(ge=0)


@router.get("")
def listing(sess=Depends(get_current_session)):
    return {"items": inbox.list_items(sess)}


@router.delete("/{ident}")
def remove(ident: str, body: Revision, sess=Depends(get_current_session)):
    with operations.reserve(inbox.identity(sess), "manual:" + ident):
        inbox.remove(ident, body.revision, sess)
    return {"deleted": True}


def _receipt(root, ident):
    with store.connection() as connection:
        rows = connection.execute("SELECT path FROM publication_intents WHERE library=? AND source=?",
                                  (str(root), "manual:" + ident)).fetchall()
    try:
        present = [row["path"] for row in rows if safe_files.private_file_exists(root, row["path"])]
    except (ValueError, OSError) as exc:
        raise HTTPException(409, "saved file cannot be verified in your library") from exc
    if len(present) > 1:
        raise HTTPException(409, "multiple publications need administrator review")
    return present[0] if present else None


async def _matching_ids(item, sess):
    # OpenSubsonic exposes the file's COMM tag as `comment`. Metadata alone
    # cannot identify our publication when another import races with scanning.
    marker = item.get("uploadMarker")
    if not marker:
        return set()
    metadata = item["track"]
    songs = await nd._search_songs_strict(metadata["title"], sess["username"], sess["salt"], sess["token"])
    return {song["id"] for song in songs
            if song.get("id") and song.get("comment") == marker
            and normalized(song.get("title") or "") == normalized(metadata["title"])
            and normalized(song.get("artist") or "") == normalized(metadata["artist"])}


def _tag_upload(path, metadata, marker):
    tagger_service.tag(str(path), metadata["artist"], metadata["title"], metadata.get("album") or "Singles")
    tags = ID3(path)
    tags.delall("COMM")
    tags.add(COMM(encoding=3, lang="eng", desc="", text=[marker]))
    tags.save(path)


async def _index(item, sess, root, library_id, path):
    if item.get("libraryRoot") != str(root):
        raise HTTPException(409, "assigned library changed; recheck the saved file")
    if item["status"] != "saved":
        item = inbox.update(item, sess, status="saved", error="index_pending")
    found = set()

    async def visible():
        nonlocal found
        db.require_active_session(sess)
        found = await _matching_ids(item, sess)
        return len(found) == 1

    try:
        target = nd.scan_target(library_id, str(root), Path(path).parent)
        indexed = await nd.scan_until(sess["username"], sess["salt"], sess["token"], done=visible,
                                      targets=[target] if target else None, timeout_s=8)
    except Exception:
        indexed = False
    db.require_active_session(sess)
    return inbox.update(item, sess, songId=next(iter(found)) if indexed and len(found) == 1 else None,
                        error=None if indexed and len(found) == 1 else "index_pending")


async def _context(ident, revision, sess):
    item = inbox.owned(ident, sess, revision)
    library_id = await nd.require_library_access(sess)
    try:
        root = safe_files.library_root(sess["library_path"])
        with safe_files.directory(root):
            pass
    except (ValueError, OSError) as exc:
        raise HTTPException(403, "assigned music directory unavailable") from exc
    if item.get("libraryRoot") and item["libraryRoot"] != str(root):
        raise HTTPException(409, "assigned library changed; review the earlier upload")
    return item, root, library_id


@router.post("/{ident}/refresh")
async def refresh(ident: str, body: Revision, sess=Depends(get_current_session)):
    with operations.reserve(inbox.identity(sess), "manual:" + ident):
        item, root, library_id = await _context(ident, body.revision, sess)
        path = _receipt(root, ident)
        if not path:
            raise HTTPException(409, "no verified uploaded file is available")
        return inbox.public(await _index(item, sess, root, library_id, path))


async def _receive(request, path, sess):
    length = request.headers.get("content-length")
    if length:
        try:
            declared = int(length)
        except ValueError as exc:
            raise HTTPException(400, "invalid upload size") from exc
        if declared < 0 or declared > MAX_UPLOAD:
            raise HTTPException(413, "MP3 exceeds the 64 MiB limit")
    total = 0
    try:
        async with asyncio.timeout(180):
            with path.open("xb") as output:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > MAX_UPLOAD:
                        raise HTTPException(413, "MP3 exceeds the 64 MiB limit")
                    db.require_active_session(sess)
                    await safe_files.run_blocking(output.write, chunk)
    except TimeoutError as exc:
        raise HTTPException(408, "upload timed out") from exc
    except ClientDisconnect as exc:
        raise HTTPException(400, "upload interrupted") from exc
    except OSError as exc:
        if exc.errno in {errno.ENOSPC, errno.EDQUOT}:
            raise HTTPException(507, "upload storage is full") from exc
        raise
    if not total:
        raise HTTPException(422, "an MP3 file is required")


async def _convert(original, converted):
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-max_alloc", str(64 * 1024**2),
        "-threads", "1", "-protocol_whitelist", "file,pipe",
        "-format_whitelist", "mp3", "-f", "mp3", "-i", str(original),
        "-map", "0:a:0", "-map_metadata", "-1", "-map_chapters", "-1", "-vn", "-sn", "-dn",
        "-fs", str(MAX_OUTPUT), "-c:a", "libmp3lame", "-threads", "1", "-b:a", "192k", str(converted),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        code = await asyncio.wait_for(process.wait(), 120)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if code != 0 or not converted.is_file() or not converted.stat().st_size:
        raise HTTPException(422, "the file could not be decoded as MP3")
    if converted.stat().st_size >= MAX_OUTPUT:
        raise HTTPException(413, "converted audio exceeds the size limit")


@router.post("/{ident}/upload")
async def upload(ident: str, request: Request,
                 revision: int = Header(ge=0, alias="X-Item-Revision"), sess=Depends(get_current_session)):
    try:
        return await _upload(ident, request, revision, sess)
    except OSError as exc:
        if exc.errno in {errno.ENOSPC, errno.EDQUOT}:
            raise HTTPException(507, "music upload storage is full") from exc
        raise HTTPException(503, "music upload processing is unavailable") from exc


async def _upload(ident, request, revision, sess):
    with operations.reserve(inbox.identity(sess), "manual:" + ident):
        item, root, library_id = await _context(ident, revision, sess)
        path = _receipt(root, ident)
        if path:
            return inbox.public(await _index(item, sess, root, library_id, path))
        if item["status"] == "saved":
            raise HTTPException(409, "previously uploaded file is missing; review your library")
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "audio/mpeg":
            raise HTTPException(415, "provide an MP3 using audio/mpeg")
        async with _upload_slot():
            with tempfile.TemporaryDirectory(prefix="music-manual-") as stage:
                original, converted = Path(stage) / "source.mp3", Path(stage) / "audio.mp3"
                await _receive(request, original, sess)
                try:
                    await _convert(original, converted)
                except TimeoutError as exc:
                    raise HTTPException(422, "MP3 conversion timed out") from exc
                reserve = int(os.environ.get("MUSIC_FREE_SPACE_RESERVE_BYTES", str(1024**3)))
                if shutil.disk_usage(root).free < converted.stat().st_size + reserve:
                    raise HTTPException(507, "library free space reserve reached")
                metadata = item["track"]
                marker = item.get("uploadMarker") or "armonia-manual:" + str(uuid.uuid4())
                await safe_files.run_blocking(_tag_upload, converted, metadata, marker)
                # The opaque marker is durable before publication. A crash
                # after rename can recover the exact file via its receipt/tag.
                item = inbox.update(item, sess, uploadMarker=marker, libraryRoot=str(root))
                current_id = await nd.require_library_access(sess)
                if current_id != library_id or str(safe_files.library_root(sess["library_path"])) != str(root):
                    raise HTTPException(409, "assigned library changed during upload")
                path = await safe_files.run_blocking(
                    safe_files.publish, converted, root, _sanitize(metadata["artist"]), _sanitize(metadata["title"]),
                    final_guard=lambda: db.active_session(sess),
                    record_intent=lambda file: publications.record(root, "manual:" + ident, file),
                )
            item = inbox.update(item, sess, status="saved", error="index_pending")
        return inbox.public(await _index(item, sess, root, library_id, path))
