"""Durable listen events and a bounded, transactional per-user delivery outbox."""
import asyncio
import json
import time
from uuid import UUID

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from homelab import artist_ids, integrations, store
from homelab.models import Track

_delivery_lock = asyncio.Lock()


class Listen(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    track: Track
    started_at: int = Field(gt=0)
    listened_seconds: float = Field(ge=0, le=86400)


def validate(event: Listen):
    now = int(time.time())
    duration = event.track.duration
    threshold = min(duration / 2, 240) if duration else 240
    if duration and duration < 30:
        raise HTTPException(422, "track is too short to count")
    if event.listened_seconds < threshold:
        raise HTTPException(422, "listening threshold not reached")
    if event.started_at > now or event.started_at < now - 90 * 86400 or event.listened_seconds > now - event.started_at + 5:
        raise HTTPException(422, "invalid listening times")


def accept(user, event: Listen, canonical=None):
    validate(event)
    from homelab.discovery_profile import fixture_reference
    if fixture_reference(canonical or event.track):
        return {"accepted": True, "duplicate": False, "ignored": "laboratory_reference"}
    now = int(time.time())
    payload = event.model_dump_json()
    with store.connection(write=True) as c:
        previous = c.execute("SELECT payload FROM play_events WHERE owner=? AND id=?", (user, str(event.id))).fetchone()
        if previous:
            if previous[0] != payload:
                raise HTTPException(409, "event id already used with different content")
            return {"accepted": True, "duplicate": True}
        pending = c.execute("SELECT count(*) FROM outbox WHERE owner=? AND state!='sent'", (user,)).fetchone()[0]
        if pending >= 5000:
            raise HTTPException(429, "listening delivery queue is full")
        resolved = event.model_copy(update={"track": canonical}).model_dump_json() if canonical else None
        c.execute("INSERT INTO play_events(owner,id,payload,created,canonical) VALUES (?,?,?,?,?)", (user, str(event.id), payload, now, resolved))
        artist_ids.remember(c, user, (canonical or event.track).model_dump(mode="json"))
        c.execute("INSERT INTO outbox(owner,event_id,destination) VALUES (?,?,'koito')", (user, str(event.id)))
    return {"accepted": True, "duplicate": False}


def payload(event):
    track = event["track"]
    info = {"listening_from": "Music Homelab"}
    if track.get("duration"):
        info["duration_ms"] = round(track["duration"] * 1000)
    if track.get("recording_mbid"):
        info["recording_mbid"] = track["recording_mbid"]
    if track.get("artist_mbids"):
        info["artist_mbids"] = track["artist_mbids"]
    if track.get("isrc"):
        info["isrc"] = track["isrc"]
    return {"listen_type": "single", "payload": [{"listened_at": event["started_at"], "track_metadata": {
        "artist_name": track["artist"], "track_name": track["title"], "release_name": track.get("album") or "",
        "additional_info": info}}]}


async def deliver_pending():
    if _delivery_lock.locked():
        return
    async with _delivery_lock:
        visited = set()
        for _ in range(25):
            now = int(time.time())
            with store.connection(write=True) as c:
                exclusions = " AND o.owner NOT IN (" + ",".join("?" for _ in visited) + ")" if visited else ""
                row = c.execute("SELECT o.*, COALESCE(e.canonical,e.payload) AS payload FROM outbox o JOIN play_events e "
                    "ON e.owner=o.owner AND e.id=o.event_id WHERE o.state IN ('pending','sending') AND o.next_try<=? "
                    + exclusions + " ORDER BY e.created LIMIT 1", (now, *sorted(visited))).fetchone()
                if not row:
                    if visited:
                        visited.clear()
                        continue
                    return
                row = dict(row)
                visited.add(row["owner"])
                # Recover automatically if delivery succeeded but its local
                # acknowledgement could not commit (disk/lock interruption).
                c.execute("UPDATE outbox SET state='sending',attempts=attempts+1,next_try=? WHERE owner=? AND event_id=? AND destination=?",
                          (now + 60, row["owner"], row["event_id"], row["destination"]))
            state, error = "pending", None
            try:
                user = row["owner"]
                config = integrations.account(user)
                async with httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False) as client:
                    response = await client.post(config["koito_url"].rstrip("/") + "/apis/listenbrainz/1/submit-listens",
                        headers={"Authorization": "Token " + integrations.koito_token(user)}, json=payload(json.loads(row["payload"])))
                    response.raise_for_status()
                state = "sent"
            except (httpx.ConnectError, httpx.ConnectTimeout):
                error = "unreachable"
            except HTTPException:
                error = "not configured"
            except httpx.HTTPStatusError as exc:
                error = f"HTTP {exc.response.status_code}"
                if 400 <= exc.response.status_code < 500 and exc.response.status_code != 429:
                    state = "blocked"
            except (httpx.HTTPError, OSError, ValueError):
                # Koito v0.3.2 INSERT OR IGNORE (track_id,listened_at) provides replay
                # deduplication for the same stable metadata/timestamp. Tested separately.
                error = "delivery uncertain; retry with identical timestamp and metadata"
            with store.connection(write=True) as c:
                c.execute("UPDATE outbox SET state=?,error=?,next_try=? WHERE owner=? AND event_id=? AND destination=?",
                    (state, error, now + min(3600, 10 * 2 ** min(row["attempts"], 8)),
                     row["owner"], row["event_id"], row["destination"]))


def recover():
    with store.connection(write=True) as c:
        c.execute("UPDATE outbox SET state='pending' WHERE state='sending' AND destination='koito'")
        # Accepted plays also back the yearly and all-time statistics.


async def worker():
    while True:
        try:
            await deliver_pending()
        except Exception:
            # No remote bodies/URLs/credentials in diagnostics. Events remain durable.
            import logging
            logging.getLogger(__name__).warning("listen delivery deferred")
        await asyncio.sleep(10)
