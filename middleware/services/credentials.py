"""Authenticated encryption for credentials at rest; keys never enter the DB."""
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet


def cipher(data_dir: Path) -> Fernet:
    configured = os.environ.get("MUSIC_SECRET_KEY_FILE")
    path = Path(configured) if configured else data_dir / "credential.key"
    if not configured and not path.exists():
        fd, temporary = tempfile.mkstemp(prefix=".key-", dir=data_dir)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(Fernet.generate_key())
                f.flush()
                os.fsync(f.fileno())
            try:
                os.link(temporary, path)  # atomic creation, no partial key readers
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        key = f.read(128).strip()
    return Fernet(key)
