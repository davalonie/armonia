import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet, RSAKey

import db
from routes import oidc as routes
from services import oidc


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "armonia.db")
    db.init_db()
    return oidc.Provider("https://auth.example/o/music/", "music", "secret",
                         "https://music.example/api/oidc/callback", "listeners")


def test_consumption_is_bound_one_time_and_expires(installation):
    key = oidc.put_ticket("mobile", "proof", {"subject": "u"}, 90)
    for kind, binding in [("login", "proof"), ("mobile", "another-client")]:
        with pytest.raises(HTTPException):
            oidc.take_ticket(key, kind, binding)
    assert oidc.take_ticket(key, "mobile", "proof") == {"subject": "u"}
    with pytest.raises(HTTPException):
        oidc.take_ticket(key, "mobile", "proof")
    expired = oidc.put_ticket("login", "browser", {}, -1)
    with pytest.raises(HTTPException):
        oidc.take_ticket(expired, "login", "browser")


def test_links_cannot_be_reassigned(installation):
    args = installation.issuer, "stable-sub", "nd-id", "local", "salt", "initial-token"
    oidc.bind(*args)
    oidc.bind(*args[:-1], "refreshed-token")
    with pytest.raises(ValueError):
        oidc.bind(args[0], args[1], "other-nd-id", *args[3:])
    with pytest.raises(ValueError):
        oidc.bind(args[0], "other-sub", *args[2:])
    with db._conn() as c:
        row = c.execute("SELECT credential FROM oidc_links").fetchone()
    assert "refreshed-token" not in row[0]
    assert oidc.unseal(row[0])["token"] == "refreshed-token"


@pytest.fixture(scope="module")
def signing_key():
    return RSAKey.generate_key(2048)


@pytest.mark.parametrize("changed", [
    {}, {"iss": "https://other.example"}, {"aud": "other-client"}, {"azp": "other-client"},
    {"nonce": "another-transaction"}, {"exp": 1}, {"sub": ""}, {"groups": ["other-group"]},
])
def test_signed_claims(installation, signing_key, changed):
    now = int(time.time())
    claims = {"iss": installation.issuer, "sub": "subject", "aud": "music", "nonce": "transaction",
              "exp": now + 60, "iat": now, "groups": ["listeners"], **changed}
    token = {"access_token": "access", "id_token": jwt.encode({"alg": "RS256"}, claims, signing_key)}
    keys = KeySet.import_key_set({"keys": [signing_key.as_dict(private=False)]})
    if changed:
        with pytest.raises((JoseError, HTTPException, ValueError)):
            oidc.validate_identity(installation, "transaction", token, keys)
    else:
        assert oidc.validate_identity(installation, "transaction", token, keys) == "subject"
        wrong = KeySet([RSAKey.generate_key(2048)])
        with pytest.raises(JoseError):
            oidc.validate_identity(installation, "transaction", token, wrong)


def test_web_start_requires_same_origin_and_disabled_is_optional(monkeypatch):
    monkeypatch.delenv("MUSIC_OIDC_ISSUER", raising=False)
    monkeypatch.setenv("MUSIC_PUBLIC_ORIGIN", "https://music.example")
    app = FastAPI()
    app.include_router(routes.router)
    c = TestClient(app)
    assert c.get("/api/oidc/config").json() == {"enabled": False}
    assert c.post("/api/oidc/web").status_code == 403
    assert c.post("/api/oidc/web", headers={"X-Music-Client": "web", "Origin": "https://elsewhere.example"}).status_code == 403
    assert c.post("/api/oidc/web", headers={"X-Music-Client": "web"}).status_code == 404
