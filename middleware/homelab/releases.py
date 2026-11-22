"""Daily release calendar, prepared from public artist metadata only.

Deezer is the main source and MusicBrainz the check. Measured on 2026-11-21 with the 29 artists of the real
account: for the same dates MusicBrainz knew 1 release and Deezer 19 (MusicBrainz, filled in by volunteers, did not
have Hard GZ's «LACOSTA 2.5», out three days before). MusicBrainz still supplies recording ids and track order, and
tells when Deezer has re-dated an old record that was uploaded again.
"""
import asyncio
import json
import os
import re
import time
import unicodedata
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid5

import httpx
from fastapi import HTTPException

import db
from homelab import discovery_profile as metadata
from homelab import generated_playlists as generated
from homelab import integrations, listening_stats, store

_tasks = {}
_resolving = {}
_resolution_slots = asyncio.Semaphore(2)
_DAY = 86400
_RETRY = 3600
_TYPES = {"Album": "Álbum", "EP": "EP", "Single": "Single"}
_DZ_TYPES = {"album": "Álbum", "ep": "EP", "single": "Single"}
_RECORDS = ("Álbum", "EP")
# Fixed namespace: a Deezer release gets the same UUID every day and in every client. The app only sends its
# session with release covers whose id has the 36 characters of a UUID (ArmoniaApplication, 0.6.1).
_DEEZER_IDS = UUID("7d6b0f0e-5a51-4c1b-9b1e-3f0c2a9d4e61")
_dz_lock = asyncio.Lock()
_next_dz = 0.0
_COVER = re.compile(r"https://cdn-images\.dzcdn\.net/images/cover/[0-9a-f]+/[0-9a-zA-Z_.-]+\.jpg")


def init():
    generated.init()
    with store.connection() as c:
        c.execute("CREATE TABLE IF NOT EXISTS release_resolved (owner TEXT, id TEXT, updated INTEGER, items TEXT, PRIMARY KEY(owner,id))")
        c.execute("CREATE TABLE IF NOT EXISTS release_cache (artist TEXT PRIMARY KEY, value TEXT, updated INTEGER)")
        c.execute("CREATE TABLE IF NOT EXISTS release_calendar (owner TEXT PRIMARY KEY, value TEXT, updated INTEGER)")


def snapshot(user):
    with store.connection() as c:
        row = c.execute("SELECT value,updated FROM release_calendar WHERE owner=?", (user,)).fetchone()
    return (json.loads(row[0]), row[1]) if row else ([], 0)


def credited(item, artist):
    return any(isinstance(a, dict) and a.get("artist", {}).get("name", "").casefold() == artist.casefold()
               for a in item.get("artist-credit", []))


def norm(text):
    """Title for comparing: no case, accents or punctuation («Todo está bien!» = «TODO ESTA BIEN»)."""
    text = unicodedata.normalize("NFKD", text or "").casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[\W_]+", " ", text).split())


def _latest_day(value):
    """Latest day a MusicBrainz date can mean: «2022» → 31-12-2022, «2022-03» → 28-03-2022."""
    value = value or ""
    if re.fullmatch(r"\d{4}", value):
        return date(int(value), 12, 31)
    if re.fullmatch(r"\d{4}-\d{2}", value):
        return date(int(value[:4]), int(value[5:]), 28)
    return date.fromisoformat(value)


async def deezer(path, params=None):
    global _next_dz
    async with _dz_lock:
        # Far below Deezer's public quota (50 requests every 5 s).
        await asyncio.sleep(max(0, _next_dz - time.monotonic()))
        _next_dz = time.monotonic() + 0.2
        data = await integrations.request_json("https://api.deezer.com/" + path,
            headers={"User-Agent": metadata.METADATA_USER_AGENT}, params=params)
    if not isinstance(data, dict) or "error" in data:
        # Deezer answers quota and lookup errors with 200 and an "error" object.
        raise HTTPException(502, "linked music service unavailable")
    return data


async def _musicbrainz_rows(artist, lower, upper):
    query = f"artist:{metadata.literal(artist)} AND firstreleasedate:[{lower} TO {upper}]"
    data = await metadata.musicbrainz("release-group", query)
    found = {}
    for release in data.get("release-groups", []):
        kind = _TYPES.get(release.get("primary-type"))
        if not kind or not credited(release, artist):
            continue
        try:
            day = date.fromisoformat(release["first-release-date"])
            key = str(UUID(release["id"]))
        except (KeyError, ValueError, TypeError):
            continue
        if lower <= day <= upper and release.get("title"):
            credit = next(a for a in release["artist-credit"] if isinstance(a, dict)
                          and a.get("artist", {}).get("name", "").casefold() == artist.casefold())
            try:
                mbid = str(UUID(credit["artist"].get("id", "")))
            except (ValueError, TypeError):
                mbid = None
            found[key] = {"id": key, "date": str(day), "type": kind, "artist": artist, "title": release["title"],
                          "tracks": [], "image": None, "artist_mbid": mbid}
    if not found:
        return found
    recordings = await metadata.musicbrainz("recording", query)
    for rec in recordings.get("recordings", []):
        if not rec.get("title") or not rec.get("id") or not credited(rec, artist):
            continue
        for edition in rec.get("releases", []):
            group = found.get(edition.get("release-group", {}).get("id"))
            if group and all(t["id"] != rec["id"] for t in group["tracks"]):
                group["tracks"].append({"id": rec["id"], "title": rec["title"], "artist": artist, "album": group["title"]})
    return found


async def _deezer_albums(artist):
    """Every release Deezer lists for the artist with exactly this name; [] when there is none."""
    found = await deezer("search/artist", {"q": artist, "limit": 10})
    exact = [a for a in found.get("data", []) if isinstance(a, dict) and a.get("id")
             and (a.get("name") or "").casefold() == artist.casefold()]
    if not exact:
        return []
    best = max(exact, key=lambda a: a.get("nb_fan") or 0)
    page = await deezer(f"artist/{int(best['id'])}/albums", {"limit": 200})
    return [a for a in page.get("data", []) if isinstance(a, dict) and a.get("id") and a.get("title")]


async def _released_before(artist, title, before):
    """True when MusicBrainz has this artist's release of the same title from before `before`. Deezer dates a record
    by its last upload: on 2026-11-21 «Mar y Tierra», Hard GZ's record from 2022, was dated 28-01-2026."""
    query = f"artist:{metadata.literal(artist)} AND releasegroup:{metadata.literal(title)}"
    for group in (await metadata.musicbrainz("release-group", query)).get("release-groups", []):
        if norm(group.get("title")) != norm(title) or not credited(group, artist):
            continue
        try:
            if _latest_day(group.get("first-release-date")) < before:
                return True
        except ValueError:
            continue
    return False


def _deezer_tracks(detail, artist, title):
    return [{"id": f"dz:{t['id']}", "title": t["title"], "artist": (t.get("artist") or {}).get("name") or artist,
             "album": title, "duration": t.get("duration") or None}
            for t in (detail.get("tracks") or {}).get("data", []) if isinstance(t, dict) and t.get("id") and t.get("title")][:100]


async def fetch_artist(artist, today):
    """(releases between 28 days before and after today, complete). Not complete: a provider failed and the artist
    is looked up again within the hour; what was found is still shown."""
    if os.environ.get("MUSIC_METADATA_PROXY_ENABLED") != "true":
        raise HTTPException(503, "metadata disabled")
    lower, upper = today-timedelta(days=28), today+timedelta(days=28)
    complete = True
    try:
        found = await _musicbrainz_rows(artist, lower, upper)
    except HTTPException:
        found, complete = {}, False
    try:
        albums = await _deezer_albums(artist)
    except HTTPException:
        if not complete:
            raise  # Both sources down: keep what was known.
        albums, complete = [], False
    known = {norm(r["title"]): r for r in found.values()}
    for album in albums:
        title = album["title"]
        cover = album.get("cover_medium") if _COVER.fullmatch(album.get("cover_medium") or "") else None
        try:
            day = date.fromisoformat(album.get("release_date") or "")
        except ValueError:
            day = None
        same = known.get(norm(title))
        if same and not same["image"]:
            same["image"] = cover
        if day is None or not lower <= day <= upper:
            continue
        try:
            detail = await deezer(f"album/{int(album['id'])}")
        except HTTPException:
            complete = False
            continue
        if same:
            # MusicBrainz already has it: Deezer adds the tracks it lacks, so a pre-release single is recognised.
            titles = {norm(t["title"]) for t in same["tracks"]}
            same["tracks"] += [t for t in _deezer_tracks(detail, artist, same["title"]) if norm(t["title"]) not in titles]
            continue
        kind = _DZ_TYPES.get(detail.get("record_type"))  # The list says «album» for EPs; the detail is right.
        names = {(c.get("name") or "").casefold() for c in detail.get("contributors", []) if isinstance(c, dict)}
        names.add(((detail.get("artist") or {}).get("name") or "").casefold())
        if not kind or artist.casefold() not in names:
            continue
        try:
            if await _released_before(artist, title, day-timedelta(days=28)):
                continue
        except HTTPException:
            complete = False  # Shown meanwhile: a MusicBrainz outage must not hide what Deezer knows.
        key = str(uuid5(_DEEZER_IDS, f"deezer:{int(album['id'])}"))
        row = {"id": key, "date": str(day), "type": kind, "artist": artist, "title": title,
               "tracks": _deezer_tracks(detail, artist, title), "image": cover, "artist_mbid": None, "source": "deezer"}
        found[key] = known[norm(title)] = row
    return list(found.values()), complete


def _cached_rows(value):
    value = json.loads(value)
    return value["rows"] if isinstance(value, dict) else value


async def _in_library(sess, row):
    """The user already has this record: a re-dated old one, or the new one already downloaded."""
    if not sess.get("username"):
        return False
    try:
        songs = await generated._local_songs(row["title"], sess)
    except Exception:  # A library lookup failure must not hide a release.
        return False
    artist = row["artist"].casefold()
    return any(norm(s.get("album")) == norm(row["title"]) and artist in (s.get("artist") or "").casefold()
               for s in songs if isinstance(s, dict))


async def artist_rows(artist, now, today):
    key = artist.casefold()
    # The same artist can appear in several accounts on the first day.
    from routes.playlist_edit import playlist_lock
    async with playlist_lock(("release-artist", key)):
        with store.connection() as c:
            row = c.execute("SELECT value,updated FROM release_cache WHERE artist=?", (key,)).fetchone()
        if row and now-row[1] < _DAY:
            cached = json.loads(row[0])
            # Rows saved before Deezer (a plain list) are looked up again.
            if isinstance(cached, dict):
                return cached["rows"], cached["complete"]
        try:
            values, complete = await fetch_artist(artist, today)
        except HTTPException:
            # A provider outage must not hide this artist for a whole day: keep what was known
            # (not marked fresh) and let the calendar try again soon.
            return (_cached_rows(row[0]) if row else []), False
        # Incomplete: looked up again within the hour instead of tomorrow.
        stamp = now if complete else now - (_DAY - _RETRY)
        with store.connection(write=True) as c:
            c.execute("INSERT OR REPLACE INTO release_cache VALUES(?,?,?)",
                      (key, json.dumps({"rows": values, "complete": complete}), stamp))
            c.execute("DELETE FROM release_cache WHERE updated<?", (now-7*_DAY,))
        return values, complete


def choose(candidates, today):
    unique, seen = {}, set()
    for group, row in candidates:
        day = date.fromisoformat(row["date"])
        # A collaboration comes once per artist; a release known to both sources, once.
        same = (norm(row["title"]), row["date"])
        if abs((day-today).days) <= 28 and row["id"] not in unique and same not in seen:
            unique[row["id"]] = (group, row)
            seen.add(same)
    ordered = sorted(unique.values(), key=lambda item: (item[0], item[1]["date"] > str(today),
                     -date.fromisoformat(item[1]["date"]).toordinal(), item[1]["title"].casefold()))
    # Only suppress a single if the album or EP actually occupies a place on the shelf. A pre-release single is
    # recognised by its recording or, across sources, by the same title from the same artist.
    selected = ordered[:20]
    for _ in range(20):
        records = [row for _, row in selected if row["type"] in _RECORDS]
        record_ids = {t["id"] for row in records for t in row["tracks"]}
        record_titles = {(row.get("artist", "").casefold(), norm(t.get("title"))) for row in records
                         for t in row["tracks"] if t.get("title")}
        eligible = []
        for group, row in ordered:
            tracks = [t for t in row["tracks"] if row["type"] != "Single" or not (t["id"] in record_ids or
                      (t.get("title") and (row.get("artist", "").casefold(), norm(t["title"])) in record_titles))]
            if tracks or not row["tracks"]:
                eligible.append((group, {**row, "tracks": tracks}))
            if len(eligible) == 20:
                break
        if [r["id"] for _, r in eligible] == [r["id"] for _, r in selected]:
            selected = eligible
            break
        selected = eligible
    rows = [{**row, "upcoming": row["date"] > str(today)} for _, row in selected]
    return sorted(rows, key=lambda r: r["upcoming"])


async def prepare(sess, user, now):
    today = datetime.fromtimestamp(now, UTC).date()
    listened = listening_stats.artist_seeds(user, now)
    similar = [a["name"] for a in generated.artists(user)]
    seen = set()
    candidates = []
    failed = False
    for group, names in enumerate((listened, similar)):
        for artist in names[:20]:
            if artist.casefold() in seen:
                continue
            seen.add(artist.casefold())
            db.require_active_session(sess)
            rows, fresh = await artist_rows(artist, now, today)
            failed |= not fresh
            for r in rows:
                # Only what came from Deezer alone: MusicBrainz has already dated the rest.
                if r.get("source") == "deezer" and await _in_library(sess, r):
                    continue
                candidates.append((group, r))
    selected = choose(candidates, today)
    db.require_active_session(sess)
    # With a provider down, the calendar is prepared again in an hour instead of tomorrow.
    stamp = now - (_DAY - _RETRY) if failed else now
    with store.connection(write=True) as c:
        c.execute("INSERT OR REPLACE INTO release_calendar VALUES(?,?,?)", (user, json.dumps(selected), stamp))
    return selected


def listing(sess, user):
    rows, last = snapshot(user)
    now = int(time.time())
    today = datetime.fromtimestamp(now, UTC).date()
    rows = [dict(r, upcoming=date.fromisoformat(r["date"]) > today) for r in rows
            if abs((date.fromisoformat(r["date"])-today).days) <= 28]
    if now-last >= _DAY and user not in _tasks:
        async def run():
            try:
                await prepare(sess, user, now)
            finally:
                _tasks.pop(user, None)
        task = asyncio.create_task(run())
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        _tasks[user] = task
    return {"preparing": user in _tasks, "items": [
        {**{k: r[k] for k in ("id", "title", "artist", "type", "date", "upcoming")}, "hasCover": bool(r["image"])}
        for r in rows]}


def lookup(user, key):
    for row in snapshot(user)[0]:
        if row["id"] == key:
            return row
    raise HTTPException(404, "Novedad no disponible")


async def cover(user, key):
    url = lookup(user, key)["image"]
    if not url or not _COVER.fullmatch(url):
        raise HTTPException(404)
    async with httpx.AsyncClient(trust_env=False, timeout=8, follow_redirects=False) as client:
        async with client.stream("GET", url) as response:
            if response.status_code != 200 or response.headers.get("content-type", "").split(";")[0] != "image/jpeg":
                raise HTTPException(404)
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 512*1024:
                    raise HTTPException(502)
    return bytes(data)


async def detail_recordings(release, active):
    # Browse by public artist MBID only. One matching edition supplies its actual disc/track order.
    artist_id = release.get("artist_mbid")
    if artist_id:
        for offset in range(0, 100, 25):
            active()
            try:
                page = await metadata.musicbrainz("release", browse={"artist": artist_id,
                    "inc": "recordings+release-groups", "offset": offset})
            except HTTPException:
                break
            editions = page.get("releases", [])
            for edition in editions:
                if edition.get("release-group", {}).get("id") != release["id"]:
                    continue
                tracks = [{"title": t.get("title") or t["recording"]["title"], "artist": release["artist"],
                           "album": release["title"], "duration": t["length"]/1000 if t.get("length") else None}
                          for medium in edition.get("media", []) for t in medium.get("tracks", [])
                          if t.get("recording", {}).get("title")]
                if tracks:
                    return tracks[:100]
            if len(editions) < 25:
                break
    return release["tracks"]


def tracks(sess, user, key):
    release = lookup(user, key)
    if release["date"] > datetime.now(UTC).date().isoformat():
        raise HTTPException(409, "Todavía no se ha publicado")
    now = int(time.time())
    with store.connection() as c:
        row = c.execute("SELECT items FROM release_resolved WHERE owner=? AND id=? AND updated>?",
                        (user, key, now-_DAY)).fetchone()
    if row:
        return {"items": json.loads(row[0]), "preparing": False}
    if (user, key) not in _resolving:
        if sum(1 for u, _ in _resolving if u == user) >= 2:
            raise HTTPException(429, "Hay dos listas en preparación")
        def active():
            db.require_active_session(sess)
        async def run():
            try:
                async with _resolution_slots:
                    items = []
                    incomplete = False
                    for recording in await detail_recordings(release, active):
                        active()
                        try:
                            item, outcome = await generated.resolve_recording(recording, sess, active)
                        except (HTTPException, httpx.HTTPError):
                            incomplete = True
                            break
                        incomplete |= outcome == "provider_error"
                        if item:
                            items.append(item)
                    active()
                    with store.connection(write=True) as c:
                        c.execute("DELETE FROM release_resolved WHERE updated<=?", (now-_DAY,))
                        c.execute("INSERT OR REPLACE INTO release_resolved VALUES(?,?,?,?)",
                                  (user, key, now - (_DAY - 300 if incomplete else 0), json.dumps(items)))
            finally:
                _resolving.pop((user, key), None)
        task = asyncio.create_task(run())
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        _resolving[user, key] = task
    return {"items": [], "preparing": True}
