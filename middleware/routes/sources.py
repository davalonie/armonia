import asyncio
import os
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from mutagen.id3 import ID3, TSRC, TXXX, UFID

import db
from auth import get_current_session
from homelab import audio_cache, operations, publications, sources
from services import navidrome_client, safe_files, tagger_service
from services.ytdlp_service import _sanitize

router = APIRouter(prefix="/api/sources", tags=["source permissions"])
_save_slots = asyncio.Semaphore(2)


@router.get("/{source}/{source_id}/capabilities")
def capabilities(source: str, source_id: str, sess=Depends(get_current_session)):
    if source == "navidrome":
        return {"stream": True, "offline": True, "cache": True, "persist": False}
    record = sources.policy(source, source_id)
    return {cap: bool(record.get("authorization")) and record.get(cap) is True
            for cap in ("stream", "offline", "cache", "persist")}


@router.post("/{source_id}/save")
async def save(source_id: str, sess=Depends(get_current_session)):
    db.require_active_session(sess)
    record = sources.allowed("authorized_http", source_id, "persist")
    library_id = await navidrome_client.require_library_access(sess)
    root = safe_files.library_root(sess["library_path"])
    metadata = record["metadata"]
    with operations.reserve(str(root), "authorized_http:" + source_id):
        publications.require_unpublished(root, "authorized_http:" + source_id)
        async with _save_slots:
            known = await navidrome_client.matching_song_ids(metadata["artist"], metadata["title"],
                sess["username"], sess["salt"], sess["token"])
            if known:
                raise HTTPException(409, "this recording is already in your library")
            try:
                audio, _ = await audio_cache.fetch(sources.audio_url(source_id, "persist"), 64 * 1024**2)
            except audio_cache.TooLarge as exc:
                raise HTTPException(413, "authorized source exceeds the import size limit") from exc
            with tempfile.TemporaryDirectory(prefix="music-import-") as stage:
                original, converted = Path(stage) / "source", Path(stage) / "audio.mp3"
                await safe_files.run_blocking(original.write_bytes, audio)
                process = await asyncio.create_subprocess_exec("ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
                    "-format_whitelist", "mp3,flac,wav,ogg,mov,matroska,webm,aac",
                    "-i", str(original), "-map", "0:a:0", "-vn", "-sn", "-fs", "100663296", "-c:a", "libmp3lame", "-b:a", "192k", str(converted),
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                try:
                    code = await asyncio.wait_for(process.wait(), timeout=120)
                except BaseException:
                    process.kill()
                    await process.wait()
                    raise
                if code != 0:
                    raise HTTPException(422, "source could not be imported as audio")
                size = converted.stat().st_size
                if size >= 100663296:
                    raise HTTPException(413, "import exceeds converted audio size limit")
                reserve = int(os.environ.get("MUSIC_FREE_SPACE_RESERVE_BYTES", str(1024**3)))
                if shutil.disk_usage(root).free < size + reserve:
                    raise HTTPException(507, "library free space reserve reached")
                await safe_files.run_blocking(tagger_service.tag, str(converted), metadata["artist"], metadata["title"], metadata.get("album") or "Singles")
                tags = ID3(converted)
                if metadata.get("artist_mbids"):
                    tags.add(TXXX(encoding=3, desc="MusicBrainz Artist Id", text=metadata["artist_mbids"]))
                if metadata.get("recording_mbid"):
                    tags.add(UFID(owner="http://musicbrainz.org", data=metadata["recording_mbid"].encode()))
                if metadata.get("isrc"):
                    tags.add(TSRC(encoding=3, text=[metadata["isrc"]]))
                tags.save(converted)
                await navidrome_client.require_library_access(sess)
                sources.allowed("authorized_http", source_id, "persist")
                file = await safe_files.run_blocking(safe_files.publish, converted, root, _sanitize(metadata["artist"]), _sanitize(metadata["title"]), final_guard=lambda: db.active_session(sess),
                    record_intent=lambda path: publications.record(root, "authorized_http:" + source_id, path))
        # Persisted successfully even if the subsequent scan is temporarily unavailable.
        try:
            target = navidrome_client.scan_target(library_id, str(root), Path(file).parent)
            indexed = await navidrome_client.scan_until(sess["username"], sess["salt"], sess["token"],
                done=lambda: navidrome_client.new_song_visible(metadata["artist"], metadata["title"], known,
                    sess["username"], sess["salt"], sess["token"]), targets=[target] if target else None)
            return {"saved": True, "indexed": indexed}
        except Exception:
            return {"saved": True, "indexed": False}
