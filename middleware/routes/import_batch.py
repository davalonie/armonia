"""Import several playlists one after another ("Importar todo Spotify").

Two origins feed the same batch: the ZIP that Exportify's "Exportar todo" downloads, and
the playlists the owner's browser read from Spotify after signing in there. The server
never holds a Spotify credential. A batch is only a queue: every playlist becomes an
ordinary import (same matcher, review and "Pendientes de añadir"), started when the
previous one stops on its own.
"""
import asyncio
import io
import json
import logging
import math
import os
import re
import time
import uuid
import zipfile
from threading import RLock
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.requests import ClientDisconnect

import db
from auth import get_current_session
from homelab.models import owner as identity_owner
from routes import import_playlist as imports
from services import navidrome_client, spotify_client, tagger_service
from services.spotify_client import SpotifyError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/import-batch", tags=["import all playlists"])

MAX_ZIP = 8 * 1024**2
MAX_MEMBER = 4 * 1024**2          # the same limit as importing one exported file
MAX_UNPACKED = 64 * 1024**2
MAX_PLAYLISTS = 200
CLIENT_KEY = "spotify_login_client_id"
_lock = RLock()


def _owner(sess):
    db.require_active_session(sess)
    return "nd:" + identity_owner(sess)


def _load(ident, user):
    with db._conn() as c:
        row = c.execute("SELECT payload FROM import_batches WHERE id=? AND owner=?", (ident, user)).fetchone()
    if row is None:
        raise HTTPException(404, "import batch not found")
    return json.loads(row["payload"])


def _save(ident, user, batch):
    with db._conn() as c:
        c.execute(
            "INSERT INTO import_batches VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "payload=excluded.payload,updated_at=excluded.updated_at",
            (ident, user, json.dumps(batch), time.time()),
        )


def _job(entry, user):
    """The import a playlist became, or None once its history was deleted."""
    ident = entry.get("importId")
    if not ident:
        return None
    job = imports._imports.get(ident)
    if job is None:
        with db._conn() as c:
            row = c.execute("SELECT payload FROM playlist_imports WHERE id=? AND owner=?", (ident, user)).fetchone()
        if row is None:
            return None
        saved = json.loads(row["payload"])
        return {"status": "paused" if saved.get("status") == "running" else saved.get("status"),
                "current": saved.get("current", 0), "total": saved.get("total", 0),
                "review": sum(i.get("state") == "review" for i in saved.get("items", [])),
                "error": saved.get("error")}
    if job.username != user:
        return None
    return {"status": job.status, "current": job.current, "total": job.total,
            "review": sum(i["state"] == "review" for i in job.items), "error": job.error}


def _public(ident, batch, user):
    playlists, running = [], False
    for index, entry in enumerate(batch["playlists"]):
        job = _job(entry, user)
        running = running or bool(job and job["status"] == "running")
        playlists.append({
            "index": index, "name": entry["name"], "total": entry["total"], "note": entry.get("note"),
            "existing": entry.get("existing", False), "state": entry["state"], "error": entry.get("error"),
            "importId": entry.get("importId"), "import": job,
        })
    status, reason = batch["status"], batch.get("reason")
    if status == "running" and not running and any(e["state"] == "running" for e in batch["playlists"]):
        # The server restarted (or the import was stopped elsewhere): nothing will call back.
        status, reason = "paused", "interrupted"
    return {"id": ident, "source": batch["source"], "status": status, "reason": reason, "playlists": playlists}


def _existing_names(user):
    with db._conn() as c:
        rows = c.execute("SELECT payload FROM playlist_imports WHERE owner=?", (user,)).fetchall()
    return {(json.loads(r["payload"]).get("name") or "").casefold() for r in rows}


def _create(source, parsed, sess):
    user = _owner(sess)
    if not parsed:
        raise HTTPException(422, "no playlists were found")
    known = _existing_names(user)
    batch = {"source": source, "status": "preview", "reason": None, "playlists": [{
        "name": p["name"], "total": len(p["tracks"]), "note": p.get("note"), "playlist": p.get("playlist"),
        "existing": p["name"].casefold() in known, "state": "idle", "importId": None, "error": None,
    } for p in parsed]}
    ident = str(uuid.uuid4())
    with _lock:
        with db._conn() as c:
            # One open proposal per user: a new upload replaces a preview never started.
            for row in c.execute("SELECT id,payload FROM import_batches WHERE owner=?", (user,)).fetchall():
                if json.loads(row["payload"])["status"] == "preview":
                    c.execute("DELETE FROM import_batches WHERE id=?", (row["id"],))
        _save(ident, user, batch)
    return _public(ident, batch, user)


def _display_name(filename):
    """Exportify names each file after its playlist, lower-cased and with "_" for spaces."""
    stem = filename.rsplit("/", 1)[-1]
    stem = re.sub(r"\.csv$", "", stem, flags=re.I).replace("_", " ").strip()
    return (stem[:1].upper() + stem[1:])[:150] or "Playlist importada"


def _parse_zip(content):
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise HTTPException(422, "the file is not a ZIP archive") from exc
    members = [m for m in archive.infolist() if not m.is_dir() and m.filename.lower().endswith(".csv")]
    if not members:
        raise HTTPException(422, "the archive contains no CSV playlists")
    if len(members) > MAX_PLAYLISTS:
        raise HTTPException(413, "the archive contains too many playlists")
    if sum(m.file_size for m in members) > MAX_UNPACKED:
        raise HTTPException(413, "the archive is too large once unpacked")
    parsed = []
    for member in members:
        name = _display_name(member.filename)
        if member.file_size > MAX_MEMBER:
            parsed.append({"name": name, "tracks": [], "note": "too_large"})
            continue
        # Read in memory with a hard cap: the declared size of a member is not trusted,
        # and nothing is ever extracted to disk.
        with archive.open(member) as source:
            raw = source.read(MAX_MEMBER + 1)
        if len(raw) > MAX_MEMBER:
            parsed.append({"name": name, "tracks": [], "note": "too_large"})
            continue
        try:
            playlist = spotify_client.parse_export(raw.decode("utf-8-sig"), name)
        except (SpotifyError, UnicodeDecodeError):
            parsed.append({"name": name, "tracks": [], "note": "unreadable"})
            continue
        parsed.append({"name": name, "tracks": playlist["tracks"], "playlist": playlist,
                       "note": playlist.get("source_warning")})
    return parsed


@router.post("/zip")
async def from_zip(request: Request, sess: dict = Depends(get_current_session)):
    """Exportify's "Exportar todo" archive: one CSV per playlist."""
    _owner(sess)
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_ZIP:
        raise HTTPException(413, "the archive exceeds the 8 MiB limit")
    content = bytearray()
    try:
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_ZIP:
                raise HTTPException(413, "the archive exceeds the 8 MiB limit")
    except ClientDisconnect as exc:
        raise HTTPException(400, "upload interrupted") from exc
    parsed = await asyncio.to_thread(_parse_zip, bytes(content))
    return _create("zip", parsed, sess)


class SourceTrack(BaseModel):
    title: str = Field(default="", max_length=300)
    artist: str = Field(default="", max_length=600)
    album: str = Field(default="", max_length=300)
    # The performers one by one, and who the album belongs to, as the source lists them.
    artists: list[Annotated[str, Field(max_length=300)]] = Field(default_factory=list, max_length=40)
    albumArtist: str = Field(default="", max_length=600)
    # Position in the album and its date, when the source states them.
    trackNumber: int | None = None
    discNumber: int | None = None
    releaseDate: str | None = Field(default=None, max_length=10)
    duration: float | None = None
    isrc: str | None = Field(default=None, max_length=32)
    sourceId: str | None = Field(default=None, max_length=128)


class SourcePlaylist(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    tracks: list[SourceTrack] = Field(max_length=10000)


class SourceBatch(BaseModel):
    playlists: list[SourcePlaylist] = Field(min_length=1, max_length=MAX_PLAYLISTS)


@router.post("/spotify")
def from_spotify(body: SourceBatch, sess: dict = Depends(get_current_session)):
    """Playlists the owner's browser read from Spotify with the owner's own sign-in there."""
    parsed = []
    for source in body.playlists:
        tracks = []
        for row in source.tracks:
            seconds = row.duration if row.duration and math.isfinite(row.duration) and 0 < row.duration <= 86400 else None
            tracks.append({
                "title": row.title.strip() or "Elemento no disponible", "artist": row.artist.strip() or "Unknown",
                "artists": tagger_service.clean_artists(row.artists), "album_artist": row.albumArtist.strip() or None,
                "album": row.album.strip(), "duration": seconds, "source_position": len(tracks),
                "source_id": row.sourceId or None, "isrc": row.isrc or None, "source_unavailable": not row.title.strip(),
                "details": tagger_service.clean_details(
                    {"track": row.trackNumber, "disc": row.discNumber, "date": row.releaseDate}),
            })
        total = len(tracks)
        tracks = tracks[:spotify_client.FILE_LIMIT]
        playlist = spotify_client._result(source.name.strip()[:150], tracks, total, "spotify_login",
                                          None if total == len(tracks) else "resource_limit") if tracks else None
        parsed.append({"name": source.name.strip()[:150], "tracks": tracks, "playlist": playlist,
                       "note": "empty" if not tracks else (playlist or {}).get("source_warning")})
    return _create("spotify", parsed, sess)


class LoginConfig(BaseModel):
    clientId: str = Field(pattern=r"^[0-9a-f]{32}$|^$")


def _client_id(user):
    """The public identifier of the owner's own Spotify application; never a secret.

    The operator may set one for everybody; otherwise each user keeps their own.
    """
    fixed = os.environ.get("MUSIC_SPOTIFY_LOGIN_CLIENT_ID", "").strip()
    if re.fullmatch(r"[0-9a-f]{32}", fixed):
        return fixed, True
    with db._conn() as c:
        row = c.execute("SELECT payload FROM music_preferences WHERE owner=? AND key=?", (user, CLIENT_KEY)).fetchone()
    return (json.loads(row["payload"]).get("clientId", "") if row else ""), False


@router.get("/config")
def config(sess: dict = Depends(get_current_session)):
    value, fixed = _client_id(_owner(sess))
    return {"spotifyClientId": value, "fixed": fixed}


@router.put("/config")
def save_config(body: LoginConfig, sess: dict = Depends(get_current_session)):
    user = _owner(sess)
    with db.active_session(sess) as c:
        c.execute("INSERT INTO music_preferences VALUES (?,?,?,?) ON CONFLICT(owner,key) DO UPDATE SET "
                  "payload=excluded.payload,updated_at=excluded.updated_at",
                  (user, CLIENT_KEY, json.dumps({"clientId": body.clientId}), time.time()))
    value, fixed = _client_id(user)
    return {"spotifyClientId": value, "fixed": fixed}


@router.get("")
def latest(sess: dict = Depends(get_current_session)):
    """The user's most recent batch, so a reload or another device finds it again."""
    user = _owner(sess)
    with db._conn() as c:
        row = c.execute("SELECT id,payload FROM import_batches WHERE owner=? ORDER BY updated_at DESC LIMIT 1",
                        (user,)).fetchone()
    return {"batch": _public(row["id"], json.loads(row["payload"]), user) if row else None}


@router.get("/{ident}")
def status(ident: str, sess: dict = Depends(get_current_session)):
    user = _owner(sess)
    return _public(ident, _load(ident, user), user)


class Start(BaseModel):
    selected: list[int] = Field(min_length=1, max_length=MAX_PLAYLISTS)
    names: dict[int, str] = Field(default_factory=dict)


@router.post("/{ident}/start")
async def start(ident: str, body: Start, sess: dict = Depends(get_current_session)):
    user = _owner(sess)
    with _lock:
        batch = _load(ident, user)
        if batch["status"] != "preview":
            raise HTTPException(409, "this batch was already started")
        chosen = set(body.selected)
        if any(i < 0 or i >= len(batch["playlists"]) for i in chosen):
            raise HTTPException(400, "invalid playlist position")
        for index, entry in enumerate(batch["playlists"]):
            if index in chosen and entry.get("playlist") and entry["total"]:
                name = (body.names.get(index) or "").strip()[:150]
                if name:
                    entry["name"] = entry["playlist"]["name"] = name
                entry["state"] = "waiting"
            else:
                entry["state"] = "skipped"
        if not any(e["state"] == "waiting" for e in batch["playlists"]):
            raise HTTPException(422, "none of the selected playlists can be imported")
        batch.update(status="running", reason=None)
        _save(ident, user, batch)
    await _advance(ident, user, sess)
    return _public(ident, _load(ident, user), user)


@router.post("/{ident}/resume")
async def resume(ident: str, sess: dict = Depends(get_current_session)):
    """Continue after a pause, an expired session or a server restart."""
    user = _owner(sess)
    with _lock:
        batch = _load(ident, user)
        if batch["status"] not in {"running", "paused"}:
            raise HTTPException(409, "this batch cannot be continued")
        for entry in batch["playlists"]:
            job = _job(entry, user)
            if entry["state"] == "running" and (job is None or job["status"] != "running"):
                # Cut short by a restart or an expired session: continue that same import
                # (positions already done are kept). One the user paused stays paused.
                entry["state"] = "running" if _restart(entry, sess) else "started"
        if any(e["state"] == "running" for e in batch["playlists"]):
            batch.update(status="running", reason=None)
            _save(ident, user, batch)
            return _public(ident, batch, user)
        batch.update(status="running", reason=None)
        _save(ident, user, batch)
    await _advance(ident, user, sess)
    return _public(ident, _load(ident, user), user)


def _restart(entry, sess):
    try:
        job = imports.owned(entry["importId"], sess)
    except HTTPException:
        return False
    if job.status != "paused" or job.cancelled or job.error not in {None, "session_expired"}:
        return False
    try:
        imports.start_worker(job, sess, None)
    except HTTPException:
        return False
    return True


class Remove(BaseModel):
    index: int = Field(ge=0)


@router.post("/{ident}/remove")
def remove(ident: str, body: Remove, sess: dict = Depends(get_current_session)):
    """Take a playlist that has not started out of the queue."""
    user = _owner(sess)
    with _lock:
        batch = _load(ident, user)
        if batch["status"] == "preview" or body.index >= len(batch["playlists"]):
            raise HTTPException(400, "invalid playlist position")
        entry = batch["playlists"][body.index]
        if entry["state"] != "waiting":
            raise HTTPException(409, "only a playlist still waiting can be removed")
        entry["state"] = "skipped"
        if batch["status"] == "running" and not any(e["state"] in {"waiting", "running"} for e in batch["playlists"]):
            batch.update(status="done", reason=None)
        _save(ident, user, batch)
    return _public(ident, batch, user)


@router.post("/{ident}/pause")
def pause(ident: str, sess: dict = Depends(get_current_session)):
    """Stop starting further playlists. The import in progress is not interrupted."""
    user = _owner(sess)
    with _lock:
        batch = _load(ident, user)
        if batch["status"] == "running":
            batch.update(status="paused", reason="user")
            _save(ident, user, batch)
    return _public(ident, batch, user)


@router.delete("/{ident}")
def forget(ident: str, sess: dict = Depends(get_current_session)):
    """Forget the queue only: imports already started, playlists and music are kept."""
    user = _owner(sess)
    with _lock:
        _load(ident, user)
        with db._conn() as c:
            c.execute("DELETE FROM import_batches WHERE id=? AND owner=?", (ident, user))
    return {"deleted": True}


async def _advance(ident, user, sess):
    """Start the next waiting playlist; one that cannot start is noted and the queue goes on."""
    while True:
        with _lock:
            batch = _load(ident, user)
            if batch["status"] != "running":
                return
            index = next((i for i, e in enumerate(batch["playlists"]) if e["state"] == "waiting"), None)
            if index is None:
                batch.update(status="done", reason=None)
                _save(ident, user, batch)
                return
            entry = batch["playlists"][index]
        try:
            library_id = await navidrome_client.require_library_access(sess)
            playlist = {**entry["playlist"], "name": entry["name"], "batch_id": ident}
            started = await imports._begin(playlist, "", None, time.perf_counter(), library_id, None, sess)
            outcome = {"state": "running", "importId": started["importId"], "error": None}
        except HTTPException as exc:
            if exc.status_code in {401, 403, 409, 429}:
                # Nothing was started. 429: another import of this user is running.
                reason = "busy" if exc.status_code == 429 else "session"
                with _lock:
                    batch = _load(ident, user)
                    batch.update(status="paused", reason=reason)
                    _save(ident, user, batch)
                return
            outcome = {"state": "failed", "error": "could_not_start"}
        except Exception as exc:  # A provider failure must not strand the rest of the queue.
            log.warning("import batch %s: playlist could not start (%s)", ident, type(exc).__name__)
            outcome = {"state": "failed", "error": "could_not_start"}
        with _lock:
            batch = _load(ident, user)
            batch["playlists"][index].update(outcome)
            _save(ident, user, batch)
        if outcome["state"] == "running":
            return


async def finished(job, sess):
    """Called by an import of a batch when its worker stops, whatever the outcome."""
    ident, user = job.source_info.get("batch_id"), job.username
    try:
        with _lock:
            try:
                batch = _load(ident, user)
            except HTTPException:
                return
            entry = next((e for e in batch["playlists"] if e.get("importId") == job.import_id), None)
            if entry is None or entry["state"] != "running":
                return  # A later resume of the same import: the queue already moved on.
            entry["state"] = "started"
            if job.cancelled or job.error in {"session_expired", "permission_denied"}:
                # The user stopped it, or nothing else could run with this session either.
                if batch["status"] == "running":
                    batch.update(status="paused", reason="user" if job.cancelled else "session")
            _save(ident, user, batch)
        await _advance(ident, user, sess)
    except Exception as exc:
        log.warning("import batch %s: could not continue (%s)", ident, type(exc).__name__)
