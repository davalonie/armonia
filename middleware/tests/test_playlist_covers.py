import io

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

import db
from auth import get_current_session
from homelab import playlist_covers, store
from homelab.models import PlaylistWrite
from routes import library, playlist_edit


@pytest.fixture
def covers(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "users.db")
    db.init_db()
    store.init()
    users = {u: db.get_session(db.create_session(u, "s", "t", user_id=u)) for u in ("ana", "eva")}
    app = FastAPI()
    app.include_router(library.router)
    app.include_router(playlist_edit.router)

    def session(account: str = Header()):
        return users[account]

    app.dependency_overrides[get_current_session] = session
    return TestClient(app)


def png(color):
    data = io.BytesIO()
    Image.new("RGB", (900, 450), color).save(data, format="PNG")
    return data.getvalue()


def test_mixed_cover_owner_resize_replace_and_delete(covers):
    p = store.write_playlist("ana", PlaylistWrite(name="Mareas", revision=0))
    key = p["id"]
    url = f"/api/playlist-covers/mixed/{key}"
    ana, eva = {"account": "ana"}, {"account": "eva"}
    assert covers.put(url, content=png("blue"), headers=eva).status_code == 404
    assert covers.put(url, content=b"texto", headers=ana).status_code == 422
    assert covers.put(url, content=b"x" * (playlist_covers.MAX_BYTES + 1), headers=ana).status_code == 413
    token = covers.put(url, content=png("blue"), headers=ana).json()["coverArt"]
    art = "/api/library/getCoverArt?id="
    assert store.playlists("ana")[0]["coverArt"] == token
    assert covers.get(art + token, headers=eva).status_code == 404
    image = Image.open(io.BytesIO(covers.get(art + token, headers=ana).content))
    assert (image.format, image.size) == ("JPEG", (640, 320))
    new = covers.put(url, content=png("red"), headers=ana).json()["coverArt"]
    assert new != token and covers.get(art + token, headers=ana).status_code == 404
    assert store.playlist("ana", key)["coverArt"] == new
    store.delete_playlist("ana", key, p["revision"])
    assert covers.get(art + new, headers=ana).status_code == 404
    with pytest.raises(HTTPException):
        playlist_covers.save("mixed", key, "ana", b"late")


def test_local_cover_uses_live_playlist_permissions(covers, monkeypatch):
    visible = {"ana": {"id": "p", "owner": "ana"}, "eva": {"id": "p", "owner": "ana"}}

    async def playlist(verb, sess, pairs):
        return visible.get(sess["username"], {})

    monkeypatch.setattr(library.navidrome_client, "import_playlist_request", playlist)
    url = "/api/playlist-covers/local/p"
    ana, eva = {"account": "ana"}, {"account": "eva"}
    assert covers.put(url, content=png("red"), headers=eva).status_code == 403
    token = covers.put(url, content=png("red"), headers=ana).json()["coverArt"]
    art = "/api/library/getCoverArt?id=" + token
    assert covers.get(art, headers=eva).headers["content-type"] == "image/jpeg"
    visible["eva"] = {"id": "different", "owner": "eva"}
    assert covers.get(art, headers=eva).status_code == 404
