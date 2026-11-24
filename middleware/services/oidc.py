"""Installation-local OIDC client and explicitly provisioned musical identities."""
import base64
import hashlib
import json
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oidc.core import CodeIDToken
from fastapi import HTTPException
from joserfc import jwt
from joserfc.jwk import KeySet

import db
from config import NAVIDROME_URL
from services import navidrome_client as nd
from services.credentials import cipher


def secure_url(url):
    p = urlsplit(url)
    if (not p.hostname or p.username or p.password or p.fragment or p.query or
            not (p.scheme == "https" or p.scheme == "http" and p.hostname in {"127.0.0.1", "localhost", "::1"})):
        raise ValueError("HTTPS required (HTTP allowed on loopback)")
    return url


@dataclass(frozen=True)
class Provider:
    issuer: str
    client_id: str
    secret: str
    callback: str
    group: str

    def client(self):
        return AsyncOAuth2Client(self.client_id, self.secret, redirect_uri=self.callback,
                                 scope="openid profile", code_challenge_method="S256",
                                 timeout=10, trust_env=False, follow_redirects=False)

    async def metadata(self):
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            r = await client.get(self.issuer.rstrip("/") + "/.well-known/openid-configuration")
            r.raise_for_status()
            meta = r.json()
        if meta["issuer"] != self.issuer:
            raise ValueError("unexpected discovery issuer")
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            secure_url(meta[key])
        return meta


def provider():
    issuer = os.environ.get("MUSIC_OIDC_ISSUER")
    if not issuer:
        raise HTTPException(404, "Authentik desactivado")
    origin = secure_url(os.environ["MUSIC_PUBLIC_ORIGIN"]).rstrip("/")
    if urlsplit(origin).path:
        raise ValueError("public origin must be an origin")
    return Provider(secure_url(issuer), os.environ["MUSIC_OIDC_CLIENT_ID"],
                    Path(os.environ["MUSIC_OIDC_SECRET_FILE"]).read_text().strip(),
                    origin + "/api/oidc/callback", os.environ.get("MUSIC_OIDC_GROUP", ""))


def digest(value):
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()).rstrip(b"=").decode()


def seal(payload):
    return cipher(db.DB_PATH.parent).encrypt(json.dumps(payload).encode()).decode()


def unseal(value):
    return json.loads(cipher(db.DB_PATH.parent).decrypt(value.encode()))


def put_ticket(kind, binding, payload, ttl):
    key = secrets.token_urlsafe(32)
    with db._conn() as c:
        c.execute("DELETE FROM oidc_tickets WHERE expires <= ?", (time.time(),))
        if c.execute("SELECT count(*) FROM oidc_tickets").fetchone()[0] >= 2048:
            raise HTTPException(429, "demasiados inicios de sesión en curso")
        c.execute("INSERT INTO oidc_tickets VALUES (?,?,?,?,?)",
                  (digest(key), kind, binding, seal(payload), time.time() + ttl))
    return key


def take_ticket(key, kind, binding):
    with db._conn() as c:
        row = c.execute("DELETE FROM oidc_tickets WHERE key=? AND kind=? AND binding=? "
                        "AND expires>? RETURNING payload", (digest(key), kind, binding, time.time())).fetchone()
    if not row:
        raise HTTPException(400, "inicio de sesión caducado o no válido")
    return unseal(row[0])


def bind(issuer, subject, uid, username, salt, token):
    credential = seal({"username": username, "salt": salt, "token": token})
    try:
        with db._conn() as c:
            cur = c.execute("INSERT INTO oidc_links VALUES (?,?,?,?) ON CONFLICT(issuer,subject) DO UPDATE "
                            "SET credential=excluded.credential WHERE user_id=excluded.user_id",
                            (issuer, subject, uid, credential))
            if cur.rowcount != 1:
                raise ValueError("la identidad ya tiene otra cuenta asignada")
    except sqlite3.IntegrityError as exc:
        raise ValueError("la cuenta musical ya tiene otra identidad asignada") from exc


async def session_for(issuer, subject):
    with db._conn() as c:
        row = c.execute("SELECT user_id,credential FROM oidc_links WHERE issuer=? AND subject=?",
                        (issuer, subject)).fetchone()
    if not row:
        raise HTTPException(403, "La cuenta de Authentik todavía no está vinculada a Armonia.")
    uid, credential = row
    grant = unseal(credential)
    username = grant["username"]
    # Native user lookup checks the immutable ID and returns today's assigned paths.
    # The UI bootstrap endpoint can auto-create users. Never use it for this lookup.
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        r = await client.get(f"{NAVIDROME_URL}/api/user/{quote(uid, safe='')}", headers={"X-Armonia-User": username})
        if r.status_code in (401, 403, 404):
            raise HTTPException(403, "Vinculación o proxy de Navidrome no válido")
        r.raise_for_status()
        user = r.json()
    if user.get("id") != uid or user.get("userName") != username:
        raise HTTPException(403, "La identidad musical ha cambiado")
    if (await nd.ping(**grant)).get("status") != "ok":
        raise HTTPException(403, "Renueva la credencial musical de esta vinculación")
    library = next((lib for lib in user.get("libraries") or [] if lib.get("path")), {})
    sid = db.create_session(**grant, user_id=uid, library_id=library.get("id"),
                            library_path=library.get("path"), is_admin=user.get("isAdmin") is True)
    return {"sessionId": sid, "userId": uid, "username": username}


async def verified_subject(config, tx, code):
    if [config.issuer, config.client_id] != tx["provider"]:
        raise ValueError("provider changed")
    meta = await config.metadata()
    async with config.client() as client:
        token = await client.fetch_token(meta["token_endpoint"], code=code, grant_type="authorization_code",
                                         code_verifier=tx["verifier"])
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        r = await client.get(meta["jwks_uri"])
        r.raise_for_status()
        keys = KeySet.import_key_set(r.json())
    return validate_identity(config, tx["nonce"], token, keys)


def validate_identity(config, nonce, token, keys):
    signed = jwt.decode(token["id_token"], keys, algorithms=["RS256"])
    claims = CodeIDToken(signed.claims, signed.header, options={"iss": {"value": config.issuer},
                          "aud": {"value": config.client_id}}, params={"nonce": nonce,
                          "client_id": config.client_id, "access_token": token["access_token"]})
    claims.validate(leeway=30)
    if not isinstance(claims["sub"], str) or not 0 < len(claims["sub"]) <= 255:
        raise ValueError("invalid subject")
    if config.group and (not isinstance(claims.get("groups"), list) or config.group not in claims["groups"]):
        raise HTTPException(403, "El grupo de Authentik no autoriza esta aplicación")
    return claims["sub"]
