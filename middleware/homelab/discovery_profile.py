"""Private seed identity and provenance adapter; Aurral remains the similarity provider.

Never send users, counts, timestamps or listen events to metadata services.
Only bounded artist/title queries go to MusicBrainz; Aurral receives artist IDs
and names. Old mixed discovery pools are deliberately not used as personal data.
"""

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID
from weakref import WeakValueDictionary

from fastapi import HTTPException

from homelab import artist_ids, integrations, store

METADATA_USER_AGENT = "ArmoniaHomelab/0.1 (private artist identity adapter)"
VERSION = 1
MAX_SEEDS = 5
_network = asyncio.Semaphore(2)
_mb_lock = asyncio.Lock()
_next_mb = 0.0
_refresh_locks = WeakValueDictionary()


def init():
    with store.connection() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS discovery_identity (owner TEXT,name TEXT,context TEXT,value TEXT,expires INTEGER,PRIMARY KEY(owner,name))"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS discovery_personal (owner TEXT PRIMARY KEY,fingerprint TEXT,value TEXT,expires INTEGER)"
        )
        c.execute("CREATE TABLE IF NOT EXISTS discovery_weekly (owner TEXT PRIMARY KEY,flow TEXT,value TEXT)")


def quarantine(user):
    path = os.environ.get("MUSIC_DISCOVERY_QUARANTINE_FILE")
    return json.loads(Path(path).read_text()).get("users", {}).get(user, {}) if path else {}


def fixture_reference(track):
    path = os.environ.get("MUSIC_DISCOVERY_QUARANTINE_FILE")
    if not path:
        return False
    refs = json.loads(Path(path).read_text()).get("fixture_references", [])
    return [track.source, track.source_id] in refs


def filter_ranking(user, ranking):
    """Exclude only manifest-proven artist IDs plus matching names, never substrings."""
    excluded = quarantine(user).get("artists", [])
    result = dict(ranking)
    result["items"] = [
        entry
        for entry in ranking.get("items", [])
        if not any(
            str(entry.get("item", {}).get("id")) == str(item["id"])
            and artist_ids.name_key(entry.get("item", {}).get("name", "")) == artist_ids.name_key(item["name"])
            for item in excluded
        )
    ]
    return result


def local_context(user, name):
    ignored = set(quarantine(user).get("event_ids", []))
    titles, ids = set(), set()
    with store.connection() as c:
        rows = c.execute(
            "SELECT id,coalesce(canonical,payload) FROM play_events WHERE owner=? ORDER BY created DESC LIMIT 5000",
            (user,),
        ).fetchall()
    for key, payload in rows:
        if key in ignored:
            continue
        track = json.loads(payload)["track"]
        if artist_ids.name_key(track["artist"]) != artist_ids.name_key(name):
            continue
        titles.add(track["title"])
        for ident in track.get("artist_mbids", []):
            try:
                ids.add(str(UUID(ident)))
            except (ValueError, TypeError):
                pass
    return sorted(titles)[:2], sorted(ids)


def cache_identity(user, name, context, result, ttl):
    with store.connection(write=True) as c:
        c.execute(
            "INSERT OR REPLACE INTO discovery_identity VALUES (?,?,?,?,?)",
            (user, artist_ids.name_key(name), context, json.dumps(result), int(time.time()) + ttl),
        )
        c.execute(
            "DELETE FROM discovery_identity WHERE owner=? AND rowid NOT IN "
            "(SELECT rowid FROM discovery_identity WHERE owner=? ORDER BY expires DESC LIMIT 200)",
            (user, user),
        )
    return result


def literal(value):
    # Escape Lucene syntax: metadata text is never a query-language fragment.
    return '"' + re.sub(r'([+\-!(){}\[\]^"~*?:\\/|&])', r"\\\1", value) + '"'


async def musicbrainz(kind, query=None, *, browse=None):
    global _next_mb
    if os.environ.get("MUSIC_METADATA_PROXY_ENABLED") != "true":
        raise HTTPException(503, "metadata disabled")
    for attempt in range(2):
        try:
            async with _mb_lock:
                await asyncio.sleep(max(0, _next_mb - time.monotonic()))
                _next_mb = time.monotonic() + 1.1
                return await integrations.request_json(
                    "https://musicbrainz.org/ws/2/" + kind + "/",
                    headers={
                        "User-Agent": METADATA_USER_AGENT,
                        "Accept": "application/json",
                    },
                    params={"fmt": "json", "limit": 25, **(browse if browse is not None else {"query": query})},
                )
        except HTTPException as exc:
            if attempt or exc.status_code != 502:
                raise


async def identify(user, artist):
    name = artist["name"]
    titles, ids = local_context(user, name)
    given = artist.get("musicbrainz_id")
    if given:
        try:
            ids = sorted(set(ids + [str(UUID(given))]))
        except (ValueError, TypeError):
            pass
    context = hashlib.sha256(json.dumps([titles, ids]).encode()).hexdigest()
    with store.connection() as c:
        row = c.execute(
            "SELECT value FROM discovery_identity WHERE owner=? AND name=? AND context=? AND expires>?",
            (user, artist_ids.name_key(name), context, int(time.time())),
        ).fetchone()
    if row:
        return json.loads(row[0])
    base = {"name": name, "mbid": None, "status": "unresolved", "reason": "missing_evidence"}
    if len(ids) > 1:
        return cache_identity(user, name, context, {**base, "status": "ambiguous", "reason": "conflicting_ids"}, 3600)
    if len(ids) == 1:
        return cache_identity(
            user,
            name,
            context,
            {**base, "mbid": ids[0], "status": "identified", "reason": "recording_metadata"},
            7 * 86400,
        )
    try:
        async with _network:
            data = await musicbrainz("artist", "artist:" + literal(name))
            candidates = {
                a["id"]: a
                for a in data.get("artists", [])
                if artist_ids.name_key(a.get("name", "")) == artist_ids.name_key(name)
            }
            if not candidates:
                return cache_identity(user, name, context, {**base, "reason": "not_found"}, 12 * 3600)
            if len(candidates) > 3:
                return cache_identity(
                    user, name, context, {**base, "status": "ambiguous", "reason": "multiple_artists"}, 12 * 3600
                )
            supported = set()
            for title in titles:
                recordings = await musicbrainz(
                    "recording", "artist:" + literal(name) + " AND recording:" + literal(title)
                )
                if recordings.get("count", 0) > 25:
                    continue
                for recording in recordings.get("recordings", []):
                    if artist_ids.name_key(recording.get("title", "")) != artist_ids.name_key(title):
                        continue
                    for credit in recording.get("artist-credit", []):
                        ident = credit.get("artist", {}).get("id")
                        if ident in candidates or artist_ids.name_key(
                            credit.get("artist", {}).get("name", "")
                        ) == artist_ids.name_key(name):
                            supported.add(ident)
            if len(supported) == 1 and supported.issubset(candidates):
                ident = str(UUID(next(iter(supported))))
                result = {**base, "status": "identified", "mbid": ident, "reason": "name_and_recording"}
                return cache_identity(user, name, context, result, 7 * 86400)
            return cache_identity(
                user,
                name,
                context,
                {
                    **base,
                    "status": "ambiguous" if len(candidates) > 1 or len(supported) > 1 else "unresolved",
                    "reason": "multiple_artists" if len(candidates) > 1 else "missing_recording_evidence",
                },
                12 * 3600,
            )
    except (HTTPException, ValueError, KeyError, TypeError):
        return cache_identity(
            user, name, context, {**base, "status": "unavailable", "reason": "metadata_unavailable"}, 60
        )


async def profile(user):
    init()
    ranking = filter_ranking(user, await integrations.koito_read(user, limit=50))
    artists = [e["item"] for e in ranking.get("items", []) if e.get("item", {}).get("name")]
    # Provider order is Koito's listening ranking. No global-library or chart seeds.
    seeds = []
    deadline = time.monotonic() + 25
    for artist in artists[:MAX_SEEDS]:
        try:
            async with asyncio.timeout(max(0.01, deadline - time.monotonic())):
                seeds.append(await identify(user, artist))
        except TimeoutError:
            seeds.append(
                {"name": artist["name"], "mbid": None, "status": "unavailable", "reason": "metadata_unavailable"}
            )
    return seeds


async def preferences(user):
    data = await integrations.aurral_request(user, "/api/discover/feedback")
    if not isinstance(data.get("feedback"), list):
        raise HTTPException(502, "private discovery preferences unavailable")
    return [entry for entry in data["feedback"] if entry.get("action") in {"block_artist", "less_like_this", "dismiss"}]


async def recommendations(user):
    # Weak entries disappear after requests finish; slow users do not block others.
    lock = _refresh_locks.setdefault(user, asyncio.Lock())
    async with lock:
        seeds = await profile(user)
        try:
            feedback = await preferences(user) if any(s["status"] == "identified" for s in seeds) else []
        except HTTPException:
            # Fail closed: do not serve artists while their private exclusions are unknown.
            return {
                "version": VERSION,
                "artists": [],
                "seeds": seeds,
                "general": [],
                "state": "unavailable",
                "partial": True,
                "period": "month",
                "generated_at": int(time.time()),
            }
        blocked_names = {artist_ids.name_key(f.get("artistName") or "") for f in feedback} - {""}
        blocked_ids = {f.get("artistId") for f in feedback} - {None, ""}
        seeds = [
            s for s in seeds if artist_ids.name_key(s["name"]) not in blocked_names and s.get("mbid") not in blocked_ids
        ]
        fingerprint = hashlib.sha256(
            json.dumps(
                [VERSION, seeds, sorted(blocked_names), sorted(str(i) for i in blocked_ids)], sort_keys=True
            ).encode()
        ).hexdigest()
        with store.connection() as c:
            row = c.execute(
                "SELECT value FROM discovery_personal WHERE owner=? AND fingerprint=? AND expires>?",
                (user, fingerprint, int(time.time())),
            ).fetchone()
        if row:
            return json.loads(row[0])
        artists = {}
        failures = False
        deadline = time.monotonic() + 20
        for seed in seeds:
            if seed["status"] != "identified":
                continue
            try:
                async with _network, asyncio.timeout(max(0.01, min(8, deadline - time.monotonic()))):
                    data = await integrations.aurral_request(
                        user,
                        "/api/artists/"
                        + seed["mbid"]
                        + "/similar?"
                        + urlencode({"artistName": seed["name"], "limit": 10}),
                    )
                for candidate in data.get("artists", [])[:10]:
                    name = candidate.get("name")
                    if not isinstance(name, str) or not name.strip() or len(name) > 300:
                        continue
                    key = artist_ids.name_key(name)
                    if key in blocked_names or candidate.get("id") in blocked_ids:
                        continue
                    if key in {artist_ids.name_key(s["name"]) for s in seeds}:
                        continue
                    entry = artists.setdefault(
                        key,
                        {
                            "name": name,
                            "sourceArtist": "",
                            "sourceType": "listening",
                            "provenance": "similar_to_identified_seed",
                            "seeds": [],
                        },
                    )
                    entry["seeds"].append({"name": seed["name"], "mbid": seed["mbid"]})
                    entry["sourceArtist"] = ", ".join(s["name"] for s in entry["seeds"])
            except (HTTPException, TimeoutError):
                failures = True
        result = {
            "version": VERSION,
            "artists": list(artists.values()),
            "seeds": seeds,
            "general": [],
            "state": "ready"
            if artists
            else (
                "unavailable"
                if failures or any(s["status"] == "unavailable" for s in seeds)
                else (
                    "no_similar_results" if any(s["status"] == "identified" for s in seeds) else "insufficient_profile"
                )
            ),
            "partial": failures,
            "period": "month",
            "generated_at": int(time.time()),
        }
        with store.connection(write=True) as c:
            c.execute(
                "INSERT OR REPLACE INTO discovery_personal VALUES (?,?,?,?)",
                (
                    user,
                    fingerprint,
                    json.dumps(result),
                    int(time.time()) + (60 if failures or not artists else 6 * 3600),
                ),
            )
        return result


def invalidate(user, name=None):
    init()
    with store.connection(write=True) as c:
        if name:
            c.execute("DELETE FROM discovery_identity WHERE owner=? AND name=?", (user, artist_ids.name_key(name)))
        else:
            c.execute("DELETE FROM discovery_identity WHERE owner=?", (user,))
        c.execute("DELETE FROM discovery_personal WHERE owner=?", (user,))


def cached_ranking(user, ranking):
    init()
    result = filter_ranking(user, ranking)
    with store.connection() as c:
        for entry in result.get("items", []):
            artist = entry.get("item", {})
            if not artist.get("name") or artist.get("musicbrainz_id"):
                continue
            row = c.execute(
                "SELECT value,context FROM discovery_identity WHERE owner=? AND name=? AND expires>?",
                (user, artist_ids.name_key(artist["name"]), int(time.time())),
            ).fetchone()
            if row:
                identity = json.loads(row[0])
                titles, ids = local_context(user, artist["name"])
                context = hashlib.sha256(json.dumps([titles, ids]).encode()).hexdigest()
                if identity.get("status") == "identified" and row[1] == context:
                    artist["musicbrainz_id"] = identity["mbid"]
    return result
