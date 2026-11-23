import gzip
import json
import time
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response

from auth import get_current_session
from homelab import integrations, listening, listening_stats, recordings, store
from homelab.models import owner

router = APIRouter(prefix="/api/listening", tags=["private statistics"])


@router.post("/events", status_code=202)
async def event(body: listening.Listen, sess=Depends(get_current_session)):
    user = owner(sess)
    listening.validate(body)
    with store.connection() as c:
        exists = c.execute("SELECT 1 FROM play_events WHERE owner=? AND id=?", (user, str(body.id))).fetchone()
    canonical = None
    if not exists and body.track.source == "navidrome":
        canonical = await recordings.local_track(body.track.source_id, sess)
    return listening.accept(user, body, canonical)


@router.get("/status")
def status(sess=Depends(get_current_session)):
    with store.connection() as c:
        rows = c.execute("SELECT state, count(*) AS count FROM outbox WHERE owner=? GROUP BY state", (owner(sess),))
        return {"delivery": {r[0]: r[1] for r in rows}}


@router.post("/retry")
def retry(sess=Depends(get_current_session)):
    # The same immutable event/timestamp is delivered again, never a new listen.
    with store.connection(write=True) as c:
        result = c.execute("UPDATE outbox SET state='pending',next_try=0,error=NULL "
            "WHERE owner=? AND state='blocked' AND destination='koito'", (owner(sess),))
        return {"queued": result.rowcount}


@router.get("/top/{kind}")
async def top(kind: str, period: str = "month", sess=Depends(get_current_session)):
    return await integrations.koito_read(owner(sess), kind, period)


@router.get("/summary")
def summary(request: Request, period: Literal["week", "month", "year", "always"] = "month",
            sess=Depends(get_current_session)):
    # The rankings are complete. For a heavy fictitious year (14,000 plays, 3,000 songs) that is ~1.5 MB of JSON and
    # nothing in front of Armonia compresses it, so this answer does (~180 KB). The phone's HTTP client asks for gzip.
    body = json.dumps(listening_stats.summary(owner(sess), period, int(time.time())), separators=(",", ":")).encode()
    if "gzip" in request.headers.get("accept-encoding", "").lower() and len(body) > 1024:
        return Response(gzip.compress(body, 6), media_type="application/json",
                        headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
    return Response(body, media_type="application/json")
