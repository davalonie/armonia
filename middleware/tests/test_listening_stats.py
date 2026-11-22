import json
import time

import db
from homelab import listening_stats, store
from services.tagger_service import DEFAULT_ALBUM


def test_periods_canonical_credit_ranking_and_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "lab.db")
    store.init()
    now = 1_800_000_000
    with store.connection(write=True) as c:
        for i, (user, ago, artist, album, seconds) in enumerate([
            ("a", 1, "A feat. B", "Álbum", 200), ("a", 4, "A", DEFAULT_ALBUM, 61),
            ("a", 9, "B", "Álbum", 300), ("b", 1, "Otro", "", 600), ("a", 150, "C", "", 95),
        ]):
            event = {"started_at": now-ago*86400, "listened_seconds": seconds, "track": {"artist": artist,
                     "album": album, "title": str(i), "source": "navidrome", "source_id": str(i)}}
            canonical = json.dumps(event)
            event["track"]["artist"] = "Antes de resolver"
            c.execute("INSERT INTO play_events(owner,id,payload,canonical,created) VALUES(?,?,?,?,?)",
                      (user, str(i), json.dumps(event), canonical, now))
    week = listening_stats.summary("a", "week", now)
    assert (week["seconds"], week["count"], week["distinct"]) == (261, 2, 1)
    assert len(week["series"]) == 7
    month = listening_stats.summary("a", "month", now)
    assert [r["name"] for r in month["artists"]] == ["B", "A"]
    assert all(r["name"] != DEFAULT_ALBUM for r in month["albums"])
    assert month["recent"][0]["track"]["title"] == "0"
    assert listening_stats.summary("a", "year", now)["count"] == 4
    assert listening_stats.summary("a", "always", now)["seconds"] == 656
    assert listening_stats.summary("empty", "month", now)["count"] == 0


def test_summary_route_sends_complete_rankings_compressed(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auth import get_current_session
    from routes import listening as routes
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "lab.db")
    store.init()
    now = int(time.time())
    with store.connection(write=True) as c:
        for i in range(3000):
            event = {"started_at": now-(i % 300)*86400-60, "listened_seconds": 180, "track": {"artist": f"Artista {i % 400}",
                     "album": f"Álbum {i % 500}", "title": f"Canción {i}", "source": "navidrome", "source_id": f"id{i}"}}
            c.execute("INSERT INTO play_events(owner,id,payload,created) VALUES(?,?,?,?)",
                      ("fixture", str(i), json.dumps(event), now))
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_session] = lambda: {"user_id": "fixture"}
    client = TestClient(app)
    packed = client.get("/api/listening/summary?period=year")
    plain = client.get("/api/listening/summary?period=year", headers={"Accept-Encoding": "identity"})
    assert packed.headers["content-encoding"] == "gzip" and "content-encoding" not in plain.headers
    assert packed.json() == plain.json() and len(plain.json()["songs"]) == 3000
    assert packed.num_bytes_downloaded*5 < plain.num_bytes_downloaded
    print(f"Año ficticio con 3.000 canciones: {plain.num_bytes_downloaded/1024:.0f} KB sin comprimir, "
          f"{packed.num_bytes_downloaded/1024:.0f} KB comprimido")
