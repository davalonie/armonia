"""Administrator-curated capabilities. Clients cannot submit remote URLs or rights."""
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException

from homelab.models import Track


def catalog():
    file = os.environ.get("MUSIC_SOURCES_FILE")
    if not file:
        return {}
    data = json.loads(Path(file).read_text())
    if not isinstance(data, dict) or len(data) > 2000:
        raise RuntimeError("invalid source catalog")
    return data


def policy(source, key):
    """Explicit recording rules override optional administrator provider access.

    Enabling a provider does not confer content rights or bypass provider checks.
    Arbitrary URLs and providers never inherit YouTube permissions.
    """
    records = catalog()
    ident = f"{source}:{key}"
    if ident in records:
        return records[ident]
    if source == "youtube" and re.fullmatch(r"[A-Za-z0-9_-]{11}", key):
        enabled = set(os.environ.get("MUSIC_YOUTUBE_CAPABILITIES", "").split(","))
        return {"authorization": "administrator-enabled provider",
                **{cap: cap in enabled for cap in ("stream", "offline", "persist")}}
    return {}


def allowed(source, key, capability):
    record = policy(source, key)
    if not record or not record.get("authorization") or record.get(capability) is not True:
        raise HTTPException(403, f"source has no configured {capability} permission")
    return record


def public_tracks(query=""):
    result = []
    for key, record in catalog().items():
        if not record.get("stream") or not record.get("authorization"):
            continue
        kind, ident = key.split(":", 1)
        track = Track(source=kind, source_id=ident, **record["metadata"])
        if all(word in f"{track.artist} {track.title} {track.album}".casefold() for word in query.casefold().split()):
            result.append(track)
    return result[:50]


def audio_url(key, capability="stream"):
    record = allowed("authorized_http", key, capability)
    url = record["url"]
    p = urlsplit(url)
    if (p.scheme not in {"https", "http"} or not p.hostname or p.username or p.password or p.fragment
            or (p.scheme == "http" and os.environ.get("MUSIC_ALLOW_HTTP_SOURCES") != "true")):
        raise HTTPException(503, "source URL is not permitted by server policy")
    return url
