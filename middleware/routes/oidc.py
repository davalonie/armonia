import os
import secrets
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from auth import COOKIE_NAME, check_web_request
from config import COOKIE_SECURE
from services import oidc

router = APIRouter(prefix="/api/oidc")
BROWSER = "armonia_oidc_browser"
PATH = "/api/oidc/callback"
# The Android app signs in through the browser and comes back to <application id>://oidc/callback.
Mobile = Literal["android", "android-debug"]
SUFFIX = {"android": "", "android-debug": ".debug"}


@router.get("/config")
def configuration():
    return {"enabled": bool(os.environ.get("MUSIC_OIDC_ISSUER"))}


async def begin(mobile=None, challenge=None):
    config = oidc.provider()
    binding, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    meta = await config.metadata()
    state = oidc.put_ticket("login", oidc.digest(binding), {"provider": [config.issuer, config.client_id],
                            "nonce": nonce, "verifier": verifier, "mobile": mobile, "challenge": challenge}, 600)
    async with config.client() as client:
        url, _ = client.create_authorization_url(meta["authorization_endpoint"], state=state,
                                                 nonce=nonce, code_verifier=verifier)
    response = RedirectResponse(url, 303) if mobile else JSONResponse({"url": url})
    response.set_cookie(BROWSER, binding, path=PATH, max_age=600, httponly=True, secure=COOKIE_SECURE, samesite="lax")
    return response


@router.post("/web")
async def web_login(request: Request):
    check_web_request(request)
    return await begin()


@router.get("/mobile")
async def mobile_login(client: Mobile, challenge: Annotated[str, Query(pattern=r"^[A-Za-z0-9_-]{43}$")]):
    return await begin(client, challenge)


@router.get("/callback")
async def callback(request: Request, state: str = Query(max_length=128), code: str = Query("", max_length=8192)):
    tx = oidc.take_ticket(state, "login", oidc.digest(request.cookies.get(BROWSER, "")))
    if not code:
        raise HTTPException(403, "Authentik no ha autorizado la sesión")
    config = oidc.provider()
    try:
        subject = await oidc.verified_subject(config, tx, code)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(401, "No se pudo validar la respuesta de Authentik") from exc
    if tx["mobile"]:
        grant = oidc.put_ticket("mobile", tx["challenge"], {"issuer": config.issuer, "subject": subject, "client": config.client_id}, 90)
        package = os.environ.get("MUSIC_ANDROID_APPLICATION_ID", "io.github.davalonie.armonia")
        callback_url = package + SUFFIX[tx["mobile"]] + "://oidc/callback"
        response = RedirectResponse(callback_url + "?" + urlencode({"code": grant}), 303)
    else:
        session = await oidc.session_for(config.issuer, subject)
        response = RedirectResponse("/?oidc=done", 303)
        response.set_cookie(COOKIE_NAME, session["sessionId"], httponly=True, secure=COOKIE_SECURE,
                            samesite="strict", max_age=30 * 86400, path="/")
    response.delete_cookie(BROWSER, path=PATH, httponly=True, secure=COOKIE_SECURE, samesite="lax")
    return response


class Exchange(BaseModel):
    code: str = Field(min_length=43, max_length=128)
    verifier: str = Field(pattern=r"^[A-Za-z0-9_-]{43,128}$")


@router.post("/exchange")
async def exchange(body: Exchange):
    config = oidc.provider()
    identity = oidc.take_ticket(body.code, "mobile", oidc.digest(body.verifier))
    if identity["issuer"] != config.issuer or identity.pop("client") != config.client_id:
        raise HTTPException(403, "El emisor ha cambiado")
    return await oidc.session_for(**identity)
