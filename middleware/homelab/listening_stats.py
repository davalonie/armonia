"""Private listening summaries. Times are accumulated before rounding for display."""
import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta

from homelab import store
from services.tagger_service import DEFAULT_ALBUM

DAYS = {"week": 7, "month": 30, "quarter": 90, "year": 365}


def primary(artist):
    # Keep ambiguous names such as bands with an ampersand intact.
    return re.split(r",|\s+(?:feat\.?|ft\.?|featuring)\s+", artist, maxsplit=1, flags=re.I)[0].strip()


def events(user, days, now):
    today = datetime.fromtimestamp(now, UTC).date()
    cutoff = int(datetime.combine(today - timedelta(days=days-1), datetime.min.time(), UTC).timestamp()) if days else 0
    with store.connection() as c:
        for row in c.execute("SELECT coalesce(canonical,payload) FROM play_events WHERE owner=? AND created>=?",
                             (user, cutoff)):
            event = json.loads(row[0])
            if cutoff <= event["started_at"] <= now:
                yield event


def artist_seeds(user, now):
    seconds = Counter()
    names = {}
    for event in events(user, 90, now):
        artist = primary(event["track"]["artist"])
        names[artist.casefold()] = artist
        seconds[artist.casefold()] += event["listened_seconds"]
    return [names[key] for key, _ in seconds.most_common(20)]


def summary(user, period, now):
    today = datetime.fromtimestamp(now, UTC).date()
    days = DAYS.get(period)
    groups = {k: {} for k in ("artists", "songs", "albums")}
    series = Counter()
    recent = []
    plays = 0
    total = 0.0
    first = today
    best = {}

    def bucket(date):
        if period == "always":
            return date.replace(day=1)
        if period == "year":
            return date - timedelta(days=date.weekday())
        return date

    for event in events(user, days, now):
        track = event["track"]
        artist = primary(track["artist"])
        artist_key = artist.casefold()
        song_key = (artist_key, track["title"].casefold())
        seconds = event["listened_seconds"]
        plays += 1
        total += seconds
        date = datetime.fromtimestamp(event["started_at"], UTC).date()
        first = min(first, date)
        series[bucket(date)] += seconds
        keys = [("songs", song_key, track["title"]), ("artists", artist_key, artist)]
        album = track.get("album")
        if album and album != DEFAULT_ALBUM:
            keys.append(("albums", (artist_key, album.casefold()), album))
        for kind, key, name in keys:
            row = groups[kind].setdefault(key, {"name": name, "seconds": 0, "count": 0, "track": track})
            row["seconds"] += seconds
            row["count"] += 1
        song = groups["songs"][song_key]
        if artist_key not in best or song["count"] > best[artist_key]["count"]:
            best[artist_key] = song
        recent.append({"at": event["started_at"], "track": track})
        if len(recent) >= 80:
            recent = sorted(recent, key=lambda r: -r["at"])[:40]

    for key, song in best.items():
        groups["artists"][key]["track"] = song["track"]
    start = today - timedelta(days=days-1) if days else first
    day = start
    while day <= today:
        series.setdefault(bucket(day), 0)
        day += timedelta(days=1)
    return {"seconds": total, "count": plays, "distinct": len(groups["artists"]),
            "series": [{"date": d.isoformat(), "seconds": series[d]} for d in sorted(series)],
            "recent": sorted(recent, key=lambda r: -r["at"])[:40],
            **{kind: sorted(rows.values(), key=lambda r: (-r["seconds"], r["name"].casefold()))
               for kind, rows in groups.items()}}
