import asyncio
import time
from collections import OrderedDict
from typing import Literal
from weakref import WeakValueDictionary

from anyio import to_thread
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from auth import get_current_session
from services import ytdlp_service

router = APIRouter()
_results = OrderedDict()
_locks = WeakValueDictionary()


class SearchRequest(BaseModel):
    scope: Literal["all", "songs", "artists"] = "all"
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)
    source: str = Field(default="youtube_music", pattern="^(youtube|youtube_music)$")


async def _cached(key, fetch):
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        cached = _results.get(key)
        if cached and time.monotonic() < cached[0]:
            _results.move_to_end(key)
            return cached[1]
        result = await to_thread.run_sync(fetch)
        if result:
            _results[key] = (time.monotonic() + 120, result)
            _results.move_to_end(key)
            if len(_results) > 128:
                _results.popitem(last=False)
        return result


@router.post("/api/search")
async def search(body: SearchRequest, sess: dict = Depends(get_current_session)):
    query = body.query.strip()
    key = (sess["id"], body.source, query)
    calls = {}
    if body.scope != "artists":
        calls["songs"] = _cached((*key, "songs", body.limit), lambda: ytdlp_service.search(query, body.limit, body.source))
    if body.scope != "songs" and body.source == "youtube_music":
        calls["artists"] = _cached((*key, "artists"), lambda: ytdlp_service.search_artists(query, 3))
    found = dict(zip(calls, await asyncio.gather(*calls.values()), strict=True))
    return {"songs": found.get("songs", []), "artists": found.get("artists", [])}
