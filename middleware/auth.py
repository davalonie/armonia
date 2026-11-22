import os

from fastapi import Header, HTTPException, Request

from db import get_session

COOKIE_NAME = "music_session"


def check_web_request(request: Request) -> None:
    """Custom header prevents form/navigation CSRF; Origin is checked when present.

    No CORS allowance is installed. Reverse proxies must preserve Host and must
    not trust client-supplied Forwarded headers (see deployment documentation).
    """
    if request.headers.get("x-music-client") != "web":
        raise HTTPException(403, "web request header required")
    origin = request.headers.get("origin")
    public = os.environ.get("MUSIC_PUBLIC_ORIGIN") or str(request.base_url)
    if origin and origin.rstrip("/") != public.rstrip("/"):
        raise HTTPException(403, "cross-origin request denied")


# Subsonic also has mutations behind GET. Cookie-authenticated callers must
# use the same CSRF protection for those, including playlist/star/scrobble.
_MEDIA_READS = {"getCoverArt", "getCoverArt.view"}


def get_current_session(
    request: Request,
    x_session_id: str | None = Header(default=None),
) -> dict:
    """Returns the session dict {id, username, salt, token, library_path, is_admin, expires_at}."""
    sid = x_session_id or request.cookies.get(COOKIE_NAME)
    if not x_session_id and sid:
        path = request.url.path
        media = request.method in {"GET", "HEAD"} and (
            path.startswith(("/api/stream/", "/api/preview/", "/api/external/"))
            or path.rsplit("/", 1)[-1] in _MEDIA_READS
        )
        if not media:
            check_web_request(request)
    if not sid:
        raise HTTPException(status_code=401, detail="not authenticated")
    s = get_session(sid)
    if s is None:
        raise HTTPException(status_code=401, detail="session expired or invalid")
    expected_owner = request.headers.get("x-music-owner")
    if expected_owner and expected_owner != s.get("user_id"):
        raise HTTPException(409, "account changed; reload before retrying")
    return s
