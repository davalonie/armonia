"""Aurral read-only adapter. Separate listener: NEVER publish port 8001.

The random URL grants only a user's top artists, not sessions or write access.
Access logging is disabled on this listener. It is reachable from private service
networks only. Possession of another user's URL grants that limited read scope.
"""
from fastapi import FastAPI, Query

from homelab import discovery_profile
from homelab.integrations import bridge_owner, koito_read

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/history/{capability}/apis/web/v1/top/artists")
async def artists(capability: str, period: str = "month", page: int = Query(default=1, ge=1, le=2),
                  limit: int = Query(default=50, ge=1, le=50)):
    user = bridge_owner(capability)
    return discovery_profile.cached_ranking(user, await koito_read(user, period=period, page=page, limit=limit))
