import asyncio
import hashlib
import json
import re
import time
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import db
from auth import get_current_session
from homelab import discovery_profile, integrations, matcher, sources, store
from homelab.models import Track, owner
from services import navidrome_client

router = APIRouter(prefix="/api", tags=["discovery"])
_flow_creation = asyncio.Lock()
_last_refresh = {}


class Link(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


@router.get("/integrations/aurral")
def link_status(sess=Depends(get_current_session)):
    with store.connection() as c:
        linked = c.execute("SELECT 1 FROM credentials WHERE owner=? AND service='aurral'",
                           (owner(sess),)).fetchone() is not None
    return {"linked": linked}


@router.post("/integrations/aurral")
async def link(body: Link, sess=Depends(get_current_session)):
    await integrations.link_aurral(owner(sess), body.username, body.password)
    return {"ok": True}


@router.delete("/integrations/aurral")
async def unlink(sess=Depends(get_current_session)):
    user = owner(sess)
    try:
        await integrations.aurral_request(user, "/api/auth/logout", "POST")
    except HTTPException:
        pass
    with store.connection(write=True) as c:
        c.execute("DELETE FROM credentials WHERE owner=? AND service='aurral'", (user,))
        c.execute("INSERT OR IGNORE INTO aurral_unlinked VALUES (?)", (user,))
    return {"ok": True}


@router.get("/discover")
async def discover(sess=Depends(get_current_session)):
    user = owner(sess)
    result = await discovery_profile.recommendations(user)
    db.require_active_session(sess)
    # No tokens, images, internal paths or raw upstream metadata in snapshots.
    with store.connection(write=True) as c:
        c.execute("INSERT INTO recommendations VALUES (?,?,?,?)",
                  (str(uuid.uuid4()), user, int(time.time()), json.dumps(result)))
        c.execute("DELETE FROM recommendations WHERE owner=? AND id NOT IN "
                  "(SELECT id FROM recommendations WHERE owner=? ORDER BY created DESC, rowid DESC LIMIT 30)", (user, user))
    return result


class RetryIdentity(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)


@router.post("/discover/refresh")
async def refresh_personal(body: RetryIdentity, sess=Depends(get_current_session)):
    user = owner(sess)
    now = time.monotonic()
    if now - _last_refresh.get("identity:" + user, -60) < 60:
        raise HTTPException(429, "Espera un minuto antes de volver a consultar los metadatos.")
    _last_refresh["identity:" + user] = now
    discovery_profile.invalidate(user, body.name)
    return await discover(sess)


def generated_size():
    from homelab import generated_playlists  # Lazy: that module imports this one lazily too.

    return generated_playlists.size()


async def weekly_config(user):
    result = await discovery_profile.recommendations(user)
    seeds = [s for s in result["seeds"] if s["status"] == "identified"]
    if not seeds:
        raise HTTPException(409, "Todavia no hay artistas identificados para tu lista semanal. Revisa las semillas en Descubrir.")
    return {"mix": {"discover": 0, "mix": 0, "trending": 0, "focus": 100, "newReleases": 0},
            "relatedArtists": [s["mbid"] for s in seeds], "recentListening": False,
            "tags": [], "autoDownload": False, "size": generated_size(), "scheduleDays": [5], "scheduleTime": "00:00"}


async def configure_weekly(user, flow_id, config):
    await integrations.aurral_request(user, "/api/playlists/flows/" + quote(flow_id, safe=""), "PUT", config)
    discovery_profile.init()
    with store.connection(write=True) as c:
        c.execute("INSERT OR REPLACE INTO discovery_weekly VALUES (?,?,?)", (user, flow_id, json.dumps(config)))


@router.get("/discover/history")
def history(sess=Depends(get_current_session)):
    with store.connection() as c:
        rows = c.execute("SELECT id,created,value FROM recommendations WHERE owner=? ORDER BY created DESC LIMIT 30", (owner(sess),))
        return {"snapshots": [{"id": r[0], "created": r[1], **json.loads(r[2])} for r in rows
                              if json.loads(r[2]).get("version") == discovery_profile.VERSION]}


@router.get("/discover/flows")
async def flows(sess=Depends(get_current_session)):
    user = owner(sess)
    remote = str(integrations.account(user).get("aurral_user_id"))
    data = await integrations.aurral_request(user, "/api/playlists/status")
    return {"flows": [{k: f.get(k) for k in ("id", "name", "autoDownload", "ownerUserId", "enabled", "nextRunAt")}
                      for f in data.get("flows", []) if str(f.get("ownerUserId")) == remote]}


@router.post("/discover/weekly")
async def weekly(sess=Depends(get_current_session)):
    """One upstream scheduled flow per user; never enable upstream downloads."""
    user = owner(sess)
    name = "Armonia Weekly " + hashlib.sha256(user.encode()).hexdigest()[:12]
    async with _flow_creation:
        config = await weekly_config(user)
        db.require_active_session(sess)
        existing = next((f for f in (await flows(sess))["flows"] if (f.get("name") or "").replace("Armon\u00eda Weekly ", "Armonia Weekly ", 1) == name), None)
        db.require_active_session(sess)
        if existing:
            if existing.get("autoDownload") is not False:
                raise HTTPException(409, "disable automatic downloads on this Aurral flow first")
            await configure_weekly(user, existing["id"], config)
            if existing.get("enabled") is not True:
                db.require_active_session(sess)
                await integrations.aurral_request(user, "/api/playlists/flows/" + quote(existing["id"], safe="") + "/enabled", "PUT", {"enabled": True})
            return {"id": existing["id"], "created": False}
        result = await integrations.aurral_request(user, "/api/playlists/flows", "POST",
            {"name": name, **config})
        created = result.get("flow", {})
        if (created.get("autoDownload") is not False or not created.get("id")
                or str(created.get("ownerUserId")) != str(integrations.account(user).get("aurral_user_id"))):
            raise HTTPException(502, "upstream did not confirm a private download-free flow")
        await configure_weekly(user, created["id"], config)
        db.require_active_session(sess)
        # Enabling the native schedule also queues its initial run; do not start twice.
        await integrations.aurral_request(user, "/api/playlists/flows/" + quote(created["id"], safe="") + "/enabled", "PUT", {"enabled": True})
        return {"id": created["id"], "created": True}


async def private_flow(flow_id, sess):
    if len(flow_id) > 128:
        raise HTTPException(422, "invalid flow id")
    user = owner(sess)
    visible = (await flows(sess))["flows"]
    chosen = next((f for f in visible if f["id"] == flow_id), None)
    if not chosen or str(chosen.get("ownerUserId")) != str(integrations.account(user).get("aurral_user_id")):
        raise HTTPException(404, "private flow not found")
    return chosen


@router.post("/discover/flows/{flow_id}/refresh")
async def refresh_flow(flow_id: str, sess=Depends(get_current_session)):
    chosen = await private_flow(flow_id, sess)
    if chosen.get("autoDownload") is not False:
        raise HTTPException(409, "disable automatic downloads on this Aurral flow first")
    user = owner(sess)
    now = time.monotonic()
    if now - _last_refresh.get(user, -60) < 60:
        raise HTTPException(429, "wait one minute before regenerating recommendations")
    _last_refresh[user] = now
    managed_name = "Armonia Weekly " + hashlib.sha256(user.encode()).hexdigest()[:12]
    if (chosen.get("name") or "").replace("Armon\u00eda Weekly ", "Armonia Weekly ", 1) == managed_name:
        config = await weekly_config(user)
        db.require_active_session(sess)
        await configure_weekly(user, flow_id, config)
    db.require_active_session(sess)
    # Custom flows keep their manual settings; only our managed Weekly is reconfigured.
    # Aurral owns the generation queue. Never call a download endpoint.
    await integrations.aurral_request(user, "/api/playlists/start/" + quote(flow_id, safe=""), "POST", {"limit": generated_size()})
    return {"queued": True}


@router.get("/discover/flows/{flow_id}")
async def flow_tracks(flow_id: str, sess=Depends(get_current_session)):
    chosen = await private_flow(flow_id, sess)
    user = owner(sess)
    personal = await discovery_profile.recommendations(user)
    name_key = discovery_profile.artist_ids.name_key
    eligible = {name_key(a["name"]) for a in personal["artists"]}
    # Aurral states which artist each focus recording is similar to. A recording tied to one of
    # this user's identified seeds is personal even when its artist is beyond the short list of
    # similar artists shown in Inicio (or is itself another seed). Blocked artists stay out.
    seeds = {s["mbid"] for s in personal["seeds"] if s.get("status") == "identified" and s.get("mbid")}
    eligible |= {name_key(s["name"]) for s in personal["seeds"] if s.get("status") == "identified"}
    blocked = None
    data = await integrations.aurral_request(user, "/api/playlists/jobs/" + quote(flow_id, safe="") + "?limit=100")
    tracks = []
    reasons = {"not_personal": 0, "blocked": 0, "invalid": 0}
    for item in data[:100]:
        key = name_key(item.get("artistName") or "")
        if key not in eligible:
            related = re.fullmatch(r"Similar to ([0-9a-f-]{36})", str(item.get("reason") or ""))
            if not related or related.group(1) not in seeds:
                reasons["not_personal"] += 1
                continue
            if blocked is None:
                try:
                    feedback = await discovery_profile.preferences(user)
                    blocked = ({name_key(f.get("artistName") or "") for f in feedback},
                               {f.get("artistId") for f in feedback} - {None, ""})
                except HTTPException:
                    blocked = False  # Exclusions unknown: fail closed for artists outside the vetted list.
            if blocked is False or key in blocked[0] or item.get("artistMbid") in blocked[1]:
                reasons["blocked"] += 1
                continue
        duration = item.get("durationMs")
        try:
            recording = Recording(title=item.get("trackName"), artist=item.get("artistName"), album=item.get("albumName") or "",
                duration=float(duration) / 1000 if duration else None, isrc=item.get("isrc"))
        except (ValueError, TypeError):
            reasons["invalid"] += 1
            continue
        tracks.append(recording.model_dump(mode="json"))
    db.require_active_session(sess)
    result = {"tracks": tracks, "autoDownload": chosen.get("autoDownload"), "provenance": "similar_to_identified_seed",
              "excluded": len(data[:100]) - len(tracks), "state": personal["state"],
              "proposed": len(data[:100]), "excludedBy": reasons}
    # Keep bounded historical snapshots of returned recommendations, independent
    # of Aurral's mutable weekly job list. No audio, links or credentials.
    if result["tracks"]:
        snapshot = {"version": discovery_profile.VERSION, "provenance": "similar_to_identified_seed", "flow": flow_id, "name": chosen.get("name"), "tracks": result["tracks"]}
        with store.connection(write=True) as c:
            value = json.dumps(snapshot)
            if not c.execute("SELECT 1 FROM recommendations WHERE owner=? AND value=?", (user, value)).fetchone():
                c.execute("INSERT INTO recommendations VALUES (?,?,?,?)", (str(uuid.uuid4()), user, int(time.time()), value))
                c.execute("DELETE FROM recommendations WHERE owner=? AND id NOT IN "
                          "(SELECT id FROM recommendations WHERE owner=? ORDER BY created DESC, rowid DESC LIMIT 30)", (user, user))
    return result


class Recording(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    artist: str = Field(min_length=1, max_length=300)
    album: str = Field(default="", max_length=300)
    duration: float | None = Field(default=None, gt=0, le=86400)
    recording_mbid: uuid.UUID | None = None
    isrc: str | None = None


@router.post("/discover/match")
async def match(body: Recording, sess=Depends(get_current_session)):
    user = owner(sess)
    key = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    with store.connection() as c:
        cached = c.execute("SELECT value FROM matches WHERE owner=? AND key=? AND expires>?", (user, key, int(time.time()))).fetchone()
    if cached:
        return json.loads(cached[0])
    query = f"{body.artist} {body.title}"
    candidates = sources.public_tracks(query)
    local = await navidrome_client.search_songs(body.title, sess["username"], sess["salt"], sess["token"], count=20)
    for row in local:
        try:
            candidates.append(Track(source="navidrome", source_id=row["id"], title=row["title"],
                artist=row.get("artist") or "Unknown", album=row.get("album") or "", duration=row.get("duration") or None))
        except (ValueError, KeyError):
            continue
    # Only administratively authorized external references enter automatic matching.
    # Existing YouTube search remains available for deliberate, reviewed selection.
    result = matcher.rank(body.model_dump(), candidates)
    with store.connection(write=True) as c:
        c.execute("DELETE FROM matches WHERE expires<=?", (int(time.time()),))
        c.execute("INSERT OR REPLACE INTO matches VALUES (?,?,?,?)", (user, key, json.dumps(result), int(time.time()) + 3600))
        c.execute("DELETE FROM matches WHERE owner=? AND rowid NOT IN (SELECT rowid FROM matches WHERE owner=? ORDER BY expires DESC LIMIT 200)", (user, user))
    return result


@router.get("/sources")
def source_catalog(sess=Depends(get_current_session)):
    return {"tracks": [t.model_dump(mode="json") for t in sources.public_tracks()]}
