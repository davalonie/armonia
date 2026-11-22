"""Personal playlists built from Aurral candidates and persisted per user.

Aurral stays the recommendation provider: it supplies weekly flow recordings and
artist similarities. This adapter only resolves those candidates to references
the existing player can stream (library first, then an administrator-permitted
external source) and stores the ordered result, so a recommendation is a real
playlist that survives reloads and devices. Nothing is downloaded or written to
Navidrome, a refresh never touches a playing queue (playback is a snapshot) and
a copy saved to the library is an independent mixed playlist.
"""

import asyncio
import json
import os
import re
import time
import uuid

from anyio import to_thread
from fastapi import HTTPException
from pydantic import ValidationError

import db
from homelab import discovery_profile, matcher, sources, store
from homelab.models import PlaylistItem, PlaylistWrite, Track
from services import navidrome_client, ytdlp_service

KEY = re.compile(r"^(weekly|similar:[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12})$")
STATUS = "@status"
ARTISTS = "@artists"
PER_ARTIST = 3
REREAD_AFTER = 24 * 3600  # Aurral's flow changes weekly; a daily re-read is cheap.
REBUILD_AFTER = 7 * 86400
WEEKLY_NAME = "Armonía semanal"
_tasks = {}
_last_manual = {}
_reports = {}  # Last weekly breakdown per user, persisted with the status row.


def size():
    """Songs per generated list; MUSIC_GENERATED_PLAYLIST_SIZE, bounded so one run stays cheap."""
    try:
        return min(50, max(10, int(os.environ.get("MUSIC_GENERATED_PLAYLIST_SIZE", "30"))))
    except ValueError:
        return 30


def init():
    with store.connection() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS generated_playlists (owner TEXT NOT NULL,key TEXT NOT NULL,"
            "name TEXT NOT NULL,description TEXT NOT NULL,items TEXT NOT NULL,state TEXT NOT NULL,"
            "error TEXT,updated INTEGER NOT NULL,PRIMARY KEY(owner,key))"
        )


def _row(user, key):
    init()
    with store.connection() as c:
        return c.execute("SELECT * FROM generated_playlists WHERE owner=? AND key=?", (user, key)).fetchone()


def _write(user, key, name, description, items, state, error=None, touch=True):
    with store.connection(write=True) as c:
        old = c.execute("SELECT updated FROM generated_playlists WHERE owner=? AND key=?", (user, key)).fetchone()
        updated = int(time.time()) if touch or not old else old[0]
        c.execute(
            "INSERT OR REPLACE INTO generated_playlists VALUES (?,?,?,?,?,?,?,?)",
            (user, key, name, description, json.dumps(items, ensure_ascii=False), state, error, updated),
        )


def cover_refs(items):
    """At most four distinct artwork references; never provider tokens or URLs we did not store."""
    refs, seen = [], set()
    for item in items:
        track = item["track"]
        ident = (track["source"], track["source_id"])
        if ident in seen:
            continue
        seen.add(ident)
        refs.append({"source": track["source"], "source_id": track["source_id"], "cover": item.get("cover")})
        if len(refs) == 4:
            break
    return refs


def _public(row, detail=False):
    items = json.loads(row["items"])
    result = {
        "key": row["key"],
        "kind": "weekly" if row["key"] == "weekly" else "similar",
        "name": row["name"],
        "description": row["description"],
        "state": row["state"],
        "error": row["error"],
        "updated": row["updated"],
        "count": len(items),
        "covers": cover_refs(items),
    }
    if detail:
        result["items"] = items
    return result


def running(user):
    task = _tasks.get(user)
    return bool(task and not task.done())


def status(user):
    row = _row(user, STATUS)
    value = json.loads(row["items"]) if row else {}
    return {
        "updating": running(user),
        "checked": row["updated"] if row else None,
        "profile": value.get("profile"),
        "weekly": value.get("weekly"),
        "error": None if running(user) or not row else row["error"],
    }


def summaries(user):
    init()
    with store.connection() as c:
        rows = c.execute(
            "SELECT * FROM generated_playlists WHERE owner=? AND key NOT LIKE '@%' ORDER BY key='weekly' DESC, rowid",
            (user,),
        ).fetchall()
    return [_public(r) for r in rows]


def detail(user, key):
    if not KEY.fullmatch(key):
        raise HTTPException(404, "playlist not found")
    row = _row(user, key)
    if not row:
        raise HTTPException(404, "playlist not found")
    return _public(row, detail=True)


def artists(user):
    row = _row(user, ARTISTS)
    return json.loads(row["items"]) if row else []


def save_copy(user, key):
    """An independent library playlist; later refreshes never rewrite it."""
    source = detail(user, key)
    if not source["items"]:
        raise HTTPException(409, "esta lista todavía no tiene canciones")
    day = time.strftime("%d/%m/%Y", time.localtime(source["updated"]))
    body = PlaylistWrite(
        name=f"{source['name']} · {day}"[:150],
        revision=0,
        items=[PlaylistItem(id=uuid.uuid4(), track=Track(**i["track"])) for i in source["items"][:500]],
    )
    return store.write_playlist(user, body)


def _same_credit(name, artist):
    return matcher.normalized(name) in matcher.credits({"title": "x", "artist": artist})[1]


def _track(source, ident, title, artist, album, duration):
    try:
        return Track(
            source=source, source_id=ident, title=title, artist=artist, album=album or "", duration=duration or None
        ).model_dump(mode="json")
    except (ValidationError, TypeError):
        return None


def _external_allowed(video):
    record = sources.policy("youtube", video or "")
    return bool(record.get("authorization")) and record.get("stream") is True


def _item(track, cover=None):
    return {"id": str(uuid.uuid4()), "track": track, "cover": cover}


async def _local_songs(query, sess):
    return await navidrome_client.search_songs(query, sess["username"], sess["salt"], sess["token"], count=20)


async def _external_songs(query, limit):
    try:
        return await to_thread.run_sync(lambda: ytdlp_service.search(query, limit=limit, source="youtube_music"))
    except Exception:  # Provider libraries raise heterogeneous errors; one failed lookup must not end the run.
        return None


def _acceptable(wanted, candidates):
    """The recommended recording, or None. Never a looser guess.

    Exact title, version and complete credits win. Recommendation providers often name
    only the main artist and no duration, so a candidate with the same main artist, the
    exact title and version, and a credit list that merely adds collaborators is the same
    proposal. If several such candidates are different recordings, abstain.
    """
    ranked = matcher.rank(wanted, candidates)["candidates"]
    for entry in ranked:
        if set(entry["reasons"]) <= {"duration unverified"}:
            return entry["track"]
    partial = [e for e in ranked if e["title_exact"] and e["credits"] == "subset"
               and set(e["reasons"]) <= {"duration unverified", "title or artist is not exact enough"}]
    if not partial:
        return None
    first = partial[0]["track"].get("duration")
    if any(abs((e["track"].get("duration") or 0) - (first or 0)) > 3 for e in partial[1:]):
        return None
    return partial[0]["track"]


async def resolve_recording(recording, sess, active):
    """One recommended recording -> (item, outcome). Outcome: local, external, no_source or provider_error."""
    wanted = {k: recording.get(k) for k in ("title", "artist", "album", "duration", "isrc")}
    local = []
    for song in await _local_songs(recording["title"], sess):
        track = _track("navidrome", song.get("id"), song.get("title"), song.get("artist"), song.get("album"), song.get("duration"))
        if track:
            local.append(Track(**track))
    chosen = _acceptable(wanted, local)
    if chosen:
        return _item(chosen), "local"
    active()
    raw = await _external_songs(f"{recording['artist']} {recording['title']}", 5)
    if raw is None:
        return None, "provider_error"
    covers, external = {}, []
    for r in raw:
        if not _external_allowed(r.get("videoId")):
            continue
        track = _track("youtube", r["videoId"], r.get("title"), r.get("channel"), r.get("album"), r.get("duration"))
        if track:
            external.append(Track(**track))
            covers[r["videoId"]] = r.get("thumbnail")
    chosen = _acceptable(wanted, external)
    return (_item(chosen, covers.get(chosen["source_id"])), "external") if chosen else (None, "no_source")


def _reusable(user, key):
    row = _row(user, key)
    known = {}
    for item in json.loads(row["items"]) if row else []:
        wanted = item.get("wanted") or [item["track"]["artist"], item["track"]["title"]]
        known[(matcher.normalized(wanted[0]), matcher.normalized(wanted[1]))] = item
    return row, known


async def build_weekly(user, sess, active, personal):
    from routes import discover  # Lazy: the route module owns Aurral flow access and provenance filtering.

    discovery_profile.init()
    with store.connection() as c:
        flow = c.execute("SELECT flow FROM discovery_weekly WHERE owner=?", (user,)).fetchone()
    description = "Canciones elegidas a partir de los artistas que más escuchas. Se renueva cada semana."
    row, known = _reusable(user, "weekly")
    previous = json.loads(row["items"]) if row else []
    if not flow:
        if previous or any(seed["status"] == "identified" for seed in personal["seeds"]):
            _write(user, "weekly", WEEKLY_NAME, description, previous, "inactive", None, touch=False)
        elif row:
            # Without identified artists the weekly list cannot be activated: do not offer it.
            with store.connection(write=True) as c:
                c.execute("DELETE FROM generated_playlists WHERE owner=? AND key='weekly'", (user,))
        return
    try:
        flow_result = await discover.flow_tracks(flow[0], sess)
        recordings = flow_result["tracks"]
    except HTTPException:
        _write(user, "weekly", WEEKLY_NAME, description, previous, "error" if not previous else "ready",
               "No se pudo consultar la lista semanal. Se conserva la última versión.", touch=False)
        return
    # Every proposal is accounted for, so a short list can be explained instead of guessed at.
    report = {"proposed": flow_result.get("proposed", len(recordings)), "eligible": len(recordings), "reused": 0,
              "local": 0, "external": 0, "no_source": 0, "provider_error": 0, "duplicate": 0, "over_limit": 0}
    items = []
    for recording in recordings[:100]:
        if len(items) >= size():
            report["over_limit"] += 1
            continue
        key = (matcher.normalized(recording["artist"]), matcher.normalized(recording["title"]))
        item = known.get(key)
        if item:
            outcome = "reused"
        else:
            item, outcome = await resolve_recording(recording, sess, active)
            if item:
                item["wanted"] = [recording["artist"], recording["title"]]
        if item and any(i["track"]["source_id"] == item["track"]["source_id"] for i in items):
            report["duplicate"] += 1
            continue
        report[outcome] += 1
        if item:
            items.append(item)
    active()
    report["listed"] = len(items)
    _reports[user] = report
    failed = report["provider_error"] > 0
    if not items:
        # Never replace a playable list with an empty one because providers failed or nothing matched.
        message = ("La lista semanal todavía se está generando en Aurral." if not recordings else
                   "No hay una fuente disponible para las canciones propuestas esta semana.")
        _write(user, "weekly", WEEKLY_NAME, description, previous, "ready" if previous else "empty", message, touch=False)
        return
    changed = [i["track"]["source_id"] for i in items] != [i["track"]["source_id"] for i in previous]
    _write(user, "weekly", WEEKLY_NAME, description, items, "ready",
           "Algunas canciones no pudieron consultarse; se reintentará." if failed else None, touch=changed or not row)


async def _artist_songs(name, sess, active, cache):
    key = matcher.normalized(name)
    if key in cache:
        return cache[key]
    found = []
    for song in await _local_songs(name, sess):
        if len(found) < PER_ARTIST and _same_credit(name, song.get("artist") or ""):
            track = _track("navidrome", song.get("id"), song.get("title"), song.get("artist"), song.get("album"), song.get("duration"))
            if track:
                found.append(_item(track))
    if len(found) < PER_ARTIST:
        active()
        for r in await _external_songs(name, 8) or []:
            if len(found) >= PER_ARTIST:
                break
            if not _external_allowed(r.get("videoId")) or not _same_credit(name, r.get("channel") or ""):
                continue
            track = _track("youtube", r["videoId"], r.get("title"), r.get("channel"), r.get("album"), r.get("duration"))
            if track and all(matcher.normalized(i["track"]["title"]) != matcher.normalized(track["title"]) for i in found):
                found.append(_item(track, r.get("thumbnail")))
    cache[key] = found
    return found


def _listed(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1]


async def build_similar(user, sess, active, personal, force):
    seeds = [s for s in personal["seeds"] if s["status"] == "identified"]
    cache = {}
    for seed in seeds:
        key = "similar:" + seed["mbid"]
        if not KEY.fullmatch(key):
            continue
        row = _row(user, key)
        if row and not force and row["state"] == "ready" and time.time() - row["updated"] < REBUILD_AFTER:
            continue
        related = [a["name"] for a in personal["artists"] if any(s["mbid"] == seed["mbid"] for s in a["seeds"])]
        if not related:
            continue
        per_artist = [await _artist_songs(name, sess, active, cache) for name in related[:10]]
        items = []
        for position in range(PER_ARTIST):  # Round-robin: variety first, never three songs in a row by one artist.
            for songs in per_artist:
                # One song credited to two similar artists must appear once.
                if (position < len(songs) and len(items) < size()
                        and all(i["track"]["source_id"] != songs[position]["track"]["source_id"] for i in items)):
                    items.append({**songs[position], "id": str(uuid.uuid4())})
        active()
        used = [name for name, songs in zip(related[:10], per_artist, strict=True) if songs]
        if not items:
            if not row:
                continue
            _write(user, key, row["name"], row["description"], json.loads(row["items"]), row["state"],
                   "No hay canciones disponibles ahora mismo; se conserva la última versión.", touch=False)
            continue
        names = ", ".join(used[:3]) + " y más" if len(used) > 3 else _listed(used)
        description = f"Artistas similares a {seed['name']}: {names}."
        _write(user, key, f"Mix {seed['name']}"[:150], description, items, "ready")
    if personal["state"] in {"ready", "no_similar_results", "insufficient_profile"}:
        # Seeds follow the monthly ranking. Drop mixes whose seed is no longer one; saved copies are untouched.
        keep = {"similar:" + s["mbid"] for s in seeds}
        with store.connection(write=True) as c:
            for (old,) in c.execute("SELECT key FROM generated_playlists WHERE owner=? AND key LIKE 'similar:%'", (user,)).fetchall():
                if old not in keep:
                    c.execute("DELETE FROM generated_playlists WHERE owner=? AND key=?", (user, old))


async def build_artists(user, active, personal, force):
    row = _row(user, ARTISTS)
    wanted = [a for a in personal["artists"]][:12]
    known = {matcher.normalized(a["name"]): a for a in (json.loads(row["items"]) if row else [])}
    result = []
    for artist in wanted:
        key = matcher.normalized(artist["name"])
        entry = None if force else known.get(key)
        if not entry:
            active()
            try:
                found = await to_thread.run_sync(lambda name=artist["name"]: ytdlp_service.search_artists(name, 3))
            except Exception:  # Same heterogeneous provider errors as searches.
                found = []
            match = next((f for f in found if matcher.normalized(f.get("name") or "") == key and f.get("channelId")), None)
            if not match:
                continue
            entry = {"name": artist["name"], "channelId": match["channelId"], "thumbnail": match.get("thumbnail")}
        result.append({**entry, "similarTo": artist["sourceArtist"]})
    active()
    if result or personal["state"] != "unavailable":
        _write(user, ARTISTS, "", "", result, "ready")


async def _run(user, sess, force):
    def active():
        db.require_active_session(sess)

    profile, error = None, None
    try:
        personal = await discovery_profile.recommendations(user)
        profile = personal["state"]
        active()
        await build_weekly(user, sess, active, personal)
        await build_similar(user, sess, active, personal, force)
        await build_artists(user, active, personal, force)
    except HTTPException as exc:
        error = ("Vincula tu cuenta de recomendaciones en Más para generar tus listas." if exc.status_code == 424 else
                 "No se pudieron actualizar tus listas. Se conservan las anteriores.")
    except Exception:  # A background refresh must record its failure instead of dying silently.
        error = "No se pudieron actualizar tus listas. Se conservan las anteriores."
    try:
        previous = _row(user, STATUS)
        before = json.loads(previous["items"]) if previous else {}
        value = {"profile": profile or before.get("profile"), "weekly": _reports.pop(user, None) or before.get("weekly")}
        _write(user, STATUS, "", "", value, "idle", error)
    except HTTPException:
        pass


def due(user):
    row = _row(user, STATUS)
    # Failed runs retry after ten minutes instead of on every visit to Inicio.
    if not row:
        return True
    weekly = _row(user, "weekly")
    # An activated flow that has not produced tracks yet, or a failed run, is retried
    # after a few minutes instead of on every visit to Inicio or only the next day.
    soon = row["error"] or (weekly and weekly["state"] == "empty")
    return time.time() - row["updated"] > (300 if soon else REREAD_AFTER)


def refresh(user, sess, force=False):
    """Start at most one background run per user; returns whether a run is active."""
    if running(user):
        return True
    if force:
        now = time.monotonic()
        if now - _last_manual.get(user, -60) < 60:
            raise HTTPException(429, "Espera un minuto antes de volver a actualizar.")
        _last_manual[user] = now
    elif not due(user):
        return False
    _tasks[user] = asyncio.get_running_loop().create_task(_run(user, dict(sess), force))
    return True
