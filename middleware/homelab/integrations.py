"""Fixed, admin-configured destinations; never accept a proxy URL from a client."""
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

import db
from homelab import artist_ids, store
from services.credentials import cipher


def fixed_origin(url):
    p = urlsplit(url)
    if (p.scheme not in {"http", "https"} or not p.hostname or p.path or p.query
            or p.fragment or p.username or p.password):
        raise ValueError("a fixed origin without credentials is required")
    return url.rstrip("/")


def configuration():
    file = os.environ.get("MUSIC_INTEGRATIONS_FILE")
    if not file:
        return {"users": {}}
    config = json.loads(Path(file).read_text())
    urls, remote_users, bridge_keys = set(), set(), set()
    for entry in config.get("users", {}).values():
        url = entry.get("koito_url", "").rstrip("/")
        if url:
            fixed_origin(url)
            if url.lower() in urls:
                raise RuntimeError("each user requires a separate Koito instance")
            urls.add(url.lower())
        remote = str(entry.get("aurral_user_id", ""))
        if remote:
            if remote in remote_users:
                raise RuntimeError("Aurral accounts cannot be shared between users")
            remote_users.add(remote)
        key = entry.get("bridge_key", "")
        if key:
            if len(key) < 43 or key in bridge_keys:
                raise RuntimeError("unique random bridge keys of at least 256 bits required")
            bridge_keys.add(key)
    return config


def account(user):
    row = configuration().get("users", {}).get(user)
    if row is None:
        raise HTTPException(503, "private integrations have not been configured for this user")
    return row


def koito_token(user):
    return Path(account(user)["koito_token_file"]).read_text().strip()


async def request_json(url, method="GET", *, headers=None, body=None, params=None):
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as c:
            async with c.stream(method, url, headers=headers, json=body, params=params) as r:
                if r.status_code in (401, 403):
                    raise HTTPException(424, "linked service requires authentication or permission")
                r.raise_for_status()
                content = bytearray()
                async for chunk in r.aiter_bytes(64 * 1024):
                    content.extend(chunk)
                    if len(content) > 4 * 1024 * 1024:
                        raise ValueError("response too large")
                return json.loads(content)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "linked music service unavailable") from exc


async def koito_read(user, kind="artists", period="month", page=1, limit=25):
    if kind not in {"artists", "tracks", "albums"} or period not in {"week", "month", "year", "all_time"}:
        raise HTTPException(422, "invalid statistics query")
    data = await request_json(account(user)["koito_url"].rstrip("/") + f"/apis/web/v1/top/{kind}",
        headers={"Authorization": "Token " + koito_token(user)},
        params={"period": period, "page": page, "limit": min(limit, 50)})
    if kind == "artists":
        with store.connection() as c:
            return artist_ids.supplement(c, user, data)
    return data


def aurral_origin():
    url = configuration().get("aurral_url", "").rstrip("/")
    try:
        return fixed_origin(url)
    except ValueError as exc:
        raise HTTPException(503, "Aurral origin is not configured") from exc


def aurral_token(user):
    with store.connection() as c:
        row = c.execute("SELECT token FROM credentials WHERE owner=? AND service='aurral'", (user,)).fetchone()
    if not row:
        raise HTTPException(424, "link your Aurral account first")
    return cipher(db.DB_PATH.parent).decrypt(row[0].encode()).decode()


async def aurral_request(user, path, method="GET", body=None):
    return await request_json(aurral_origin() + path, method,
        headers={"Authorization": "Bearer " + aurral_token(user)}, body=body)


async def link_aurral(user, username, password):
    configured = account(user)
    bridge = fixed_origin(configuration().get("bridge_origin", "http://music:8001").rstrip("/"))
    key = configured.get("bridge_key")
    if not key or not configured.get("aurral_user_id"):
        raise HTTPException(503, "private history bridge has not been provisioned")
    remote = await request_json(aurral_origin() + "/api/auth/login", "POST", body={"username": username, "password": password})
    if str(remote.get("user", {}).get("id")) != str(configured.get("aurral_user_id")):
        raise HTTPException(403, "this Aurral account is not assigned to your user")
    token = remote.get("token")
    if not isinstance(token, str) or not token:
        raise HTTPException(502, "invalid Aurral login response")
    # Link only after the scoped read-only bridge has been accepted upstream.
    await request_json(aurral_origin() + "/api/users/me/listening-history", "PATCH",
                       headers={"Authorization": "Bearer " + token},
                       body={"koito": f"{bridge}/history/{key}", "lastfm": None, "listenbrainz": None})
    with store.connection(write=True) as c:
        c.execute("INSERT INTO credentials VALUES (?, 'aurral', ?, ?) ON CONFLICT(owner,service) DO UPDATE SET "
                  "remote_id=excluded.remote_id, token=excluded.token",
                  (user, str(remote["user"]["id"]), cipher(db.DB_PATH.parent).encrypt(token.encode()).decode()))


def bridge_owner(key):
    if len(key) < 43:
        raise HTTPException(404, "not found")
    for user, row in configuration().get("users", {}).items():
        if secrets.compare_digest(key, row.get("bridge_key", "")):
            return user
    raise HTTPException(404, "not found")
