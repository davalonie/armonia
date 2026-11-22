import hashlib
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import InvalidToken
from fastapi import HTTPException

from config import DATA_DIR
from services.credentials import cipher

DB_PATH = Path(DATA_DIR) / "armonia.db"


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA secure_delete=ON")
        # Pre-token sessions stored the cleartext Navidrome password. If we find
        # that old schema, drop the table so no plaintext lingers; users simply
        # re-login and the new schema persists only a derived Subsonic
        # (salt, token) pair plus the resolved library path.
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        ).fetchone()
        if existing:
            scols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
            if "token" not in scols:
                conn.execute("DROP TABLE sessions")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                salt TEXT NOT NULL,
                token TEXT NOT NULL,
                library_path TEXT,
                is_admin INTEGER NOT NULL DEFAULT 0,
                expires_at INTEGER NOT NULL
            )
        """)
        # Migrate token-schema DBs that predate the is_admin column. Existing
        # sessions default to non-admin until the user logs in again.
        scols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        if "is_admin" not in scols:
            conn.execute("ALTER TABLE sessions ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        # Navidrome library id, for targeted (single-folder) scans. Older sessions
        # leave it NULL and resolve it on demand (see navidrome_client).
        if "library_id" not in scols:
            conn.execute("ALTER TABLE sessions ADD COLUMN library_id INTEGER")
        if "credential_version" not in scols:
            # Re-login once when upgrading: revoke URL-exposed legacy bearers.
            conn.execute("DELETE FROM sessions")
            conn.execute("ALTER TABLE sessions ADD COLUMN credential_version INTEGER NOT NULL DEFAULT 1")
        if "user_id" not in scols:
            conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
        # Hygiene: drop sessions that have already expired (they're filtered on
        # read anyway, this just stops the table accumulating dead rows).
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                album TEXT,
                source TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                file_path TEXT,
                file_size_bytes INTEGER,
                started_at INTEGER NOT NULL,
                completed_at INTEGER
            )
        """)
        # Migrate older DBs that predate the album/source columns.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(downloads)").fetchall()}
        if "album" not in cols:
            conn.execute("ALTER TABLE downloads ADD COLUMN album TEXT")
        if "source" not in cols:
            conn.execute("ALTER TABLE downloads ADD COLUMN source TEXT")
        # Downloads are now owned per-user. The very first run with this column
        # absent is the migration point: pre-existing rows have no owner, so we
        # drop the old (globally-visible) history rather than orphan it.
        if "username" not in cols:
            conn.execute("ALTER TABLE downloads ADD COLUMN username TEXT")
            conn.execute("DELETE FROM downloads")

        conn.execute("""CREATE TABLE IF NOT EXISTS playlist_imports (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload TEXT NOT NULL,
            updated_at REAL NOT NULL
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS manual_inbox (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, origin_import_id TEXT NOT NULL,
            origin_index INTEGER NOT NULL, payload TEXT NOT NULL, revision INTEGER NOT NULL,
            updated_at REAL NOT NULL, UNIQUE(owner,origin_import_id,origin_index)
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS import_batches (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS music_preferences (
            owner TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL,
            updated_at REAL NOT NULL, PRIMARY KEY(owner,key)
        )""")

        # Job state lives in memory (see jobs.py) and doesn't survive a restart.
        # Any row still marked in-flight at startup is therefore orphaned from a
        # previous process — flip it to error so it doesn't sit "downloading"
        # forever, and so the UI offers a retry instead of polling a dead job.
        conn.execute(
            """
            UPDATE downloads
               SET status = 'error',
                   error = 'interrupted by restart',
                   completed_at = ?
             WHERE status IN ('pending', 'downloading', 'tagging', 'scanning')
            """,
            (int(time.time()),),
        )


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=.1)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except sqlite3.OperationalError as exc:
        conn.rollback()
        if getattr(exc, "sqlite_errorcode", 0) & 0xff in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise HTTPException(503, "session database temporarily busy", headers={"Retry-After": "1"}) from exc
        raise
    finally:
        conn.close()


def session_key(sid: str) -> str:
    return hashlib.sha256(sid.encode()).hexdigest()


SESSION_TTL_DAYS = 30
# Sliding expiry: a session in active use is renewed to the full TTL, at most
# once per day so the write doesn't happen on every request.
_SESSION_RENEW_AFTER_S = 86400


def create_session(
    username: str, salt: str, token: str, library_path: str | None = None,
    is_admin: bool = False, ttl_days: int = SESSION_TTL_DAYS,
    library_id: int | None = None, user_id: str | None = None,
) -> str:
    sid = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + ttl_days * 86400
    with _conn() as c:
        c.execute(
            "INSERT INTO sessions (id, username, salt, token, library_path, is_admin, expires_at, library_id, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_key(sid), username, salt, cipher(DB_PATH.parent).encrypt(token.encode()).decode(),
             library_path, int(is_admin), expires_at, library_id, user_id),
        )
    return sid


def delete_expired_sessions() -> int:
    """Purge sessions past their expiry. Returns the number removed."""
    with _conn() as c:
        cur = c.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
        return cur.rowcount


def get_session(sid: str) -> dict | None:
    now = int(time.time())
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM sessions WHERE id = ? AND expires_at > ?",
            (session_key(sid), now),
        ).fetchone()
        if row is None:
            return None
        s = dict(row)
        try:
            s["token"] = cipher(DB_PATH.parent).decrypt(s["token"].encode()).decode()
        except (InvalidToken, UnicodeError):
            return None
        s["id"] = sid
        full = now + SESSION_TTL_DAYS * 86400
        if s["expires_at"] <= full - _SESSION_RENEW_AFTER_S:
            c.execute("UPDATE sessions SET expires_at = ? WHERE id = ?", (full, session_key(sid)))
            s["expires_at"] = full
    return s


def delete_session(sid: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE id = ?", (session_key(sid),))


@contextmanager
def active_session(sess: dict):
    """A short transaction linearizes final file publication with local logout.

    Never hold this over network I/O or file copying. BEGIN IMMEDIATE makes a
    concurrent logout wait until the tiny final rename/unlink has committed.
    It does not renew expiry or decrypt reusable provider credentials.
    """
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        valid = sess.get("id") and c.execute(
            "SELECT 1 FROM sessions WHERE id=? AND user_id=? AND expires_at>?",
            (session_key(sess["id"]), sess.get("user_id"), int(time.time())),
        ).fetchone()
        if not valid:
            raise HTTPException(401, "session expired or revoked")
        yield c


def check_session(sess: dict) -> None:
    """Read-only revocation check for open audio responses: 401 if logged out or expired.

    Unlike active_session it takes no write lock, so a stream checking twice a second
    neither waits behind nor blocks an import or download that is writing.
    """
    with _conn() as c:
        valid = sess.get("id") and c.execute(
            "SELECT 1 FROM sessions WHERE id=? AND user_id=? AND expires_at>?",
            (session_key(sess["id"]), sess.get("user_id"), int(time.time())),
        ).fetchone()
    if not valid:
        raise HTTPException(401, "session expired or revoked")


def require_active_session(sess: dict) -> None:
    with active_session(sess):
        pass


# ── Downloads ────────────────────────────────────────────────────────────────

def upsert_download(
    id_: str,
    video_id: str,
    artist: str,
    title: str,
    status: str,
    *,
    username: str | None = None,
    album: str | None = None,
    source: str | None = None,
    error: str | None = None,
    file_path: str | None = None,
    file_size_bytes: int | None = None,
    started_at: int | None = None,
    completed_at: int | None = None,
) -> None:
    with _conn() as c:
        c.execute(
            """
            INSERT INTO downloads
                (id, video_id, artist, title, username, album, source, status, error,
                 file_path, file_size_bytes, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status          = excluded.status,
                error           = excluded.error,
                username        = COALESCE(excluded.username,        username),
                album           = COALESCE(excluded.album,           album),
                source          = COALESCE(excluded.source,          source),
                file_path       = COALESCE(excluded.file_path,       file_path),
                file_size_bytes = COALESCE(excluded.file_size_bytes, file_size_bytes),
                completed_at    = COALESCE(excluded.completed_at,    completed_at)
            """,
            (
                id_, video_id, artist, title, username, album, source, status, error,
                file_path, file_size_bytes, started_at or int(time.time()), completed_at,
            ),
        )


def list_downloads(username: str | None = None, is_admin: bool = False) -> list[dict]:
    """List downloads for a user. Admins (or username=None) see everything."""
    with _conn() as c:
        if is_admin or username is None:
            rows = c.execute(
                "SELECT * FROM downloads ORDER BY started_at DESC LIMIT 200"
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM downloads WHERE username = ? ORDER BY started_at DESC LIMIT 200",
                (username,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_download_record(id_: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM downloads WHERE id = ?", (id_,)).fetchone()
    return dict(row) if row else None


def delete_download_record(id_: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM downloads WHERE id = ?", (id_,))
