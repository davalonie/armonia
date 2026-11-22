"""Linux filesystem operations anchored to open directory descriptors.

Never resolve symlinks, guess a file by tags, or fall back to another library.
Only a dedicated music tree may be configured. Other host paths must not be
mounted into the container. Untrusted processes must not own its parent mount.
"""
import asyncio
import os
import shutil
import stat
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path

from config import MUSIC_DIR


async def run_blocking(fn, *args, **kwargs):
    """Keep enclosing reservations/staging alive until a disk worker finishes."""
    task = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        try:
            task.result()
        finally:
            raise asyncio.CancelledError() from None


def library_root(library_path: str | None, music_dir: str | None = None) -> Path:
    root = Path(music_dir or MUSIC_DIR)
    candidate = Path(library_path) if library_path else root
    if not root.is_absolute() or not candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("invalid library root")
    candidate.relative_to(root)  # lexical check only: traversal below uses NOFOLLOW
    return candidate


@contextmanager
def directory(path: Path, *, create: bool = False):
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("absolute contained directory required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def relative_file(root: Path, reported: str) -> Path:
    p = Path(reported)
    if ".." in p.parts or not reported or "\x00" in reported:
        raise ValueError("invalid music path")
    if p.is_absolute():
        p = p.relative_to(root)
    if not p.parts or p.name in {"", ".", ".."}:
        raise ValueError("invalid music path")
    return p


def unlink_music(root: Path, reported: str) -> Path:
    rel = relative_file(root, reported)
    with directory(root / rel.parent) as fd:
        st = os.stat(rel.name, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise ValueError("not a private regular music file")
        # unlink never follows the final component, including a concurrent swap.
        os.unlink(rel.name, dir_fd=fd)
    return root / rel


def private_file_exists(root: Path, reported: str) -> bool:
    """Check a recorded publication without following any symlink or opening it."""
    rel = relative_file(root, reported)
    try:
        with directory(root / rel.parent) as fd:
            st = os.stat(rel.name, dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                raise ValueError("not a private regular music file")
            return True
    except FileNotFoundError:
        return False


def publish(staged: Path, root: Path, artist: str, stem: str, final_guard=nullcontext, record_intent=None) -> str:
    """Copy a tagged private staging file; never open an existing library file.

    UUID filenames preserve older downloads and prevent overwrite races. A
    partially written file stays hidden until rename within the same dirfd.
    """
    if any(Path(s).name != s or s in {"", ".", ".."} for s in (artist, stem)):
        raise ValueError("invalid filename")
    with directory(root):
        pass  # roots must already exist; do not create arbitrary host trees
    with directory(root / artist, create=True) as fd:
        unique = uuid.uuid4().hex
        name = f"{stem[:180]} [{unique}]{staged.suffix}"
        temp = f".import-{unique}"
        out = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with os.fdopen(out, "wb") as dst, staged.open("rb") as src:
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
            # Commit the destination before rename. A restart can distinguish
            # an unfinished intention from a published but not yet indexed file.
            # Do not nest this database write inside final_guard's transaction.
            if record_intent:
                record_intent(str(root / artist / name))
            with final_guard():
                os.rename(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
                os.fsync(fd)
        finally:
            try:
                os.unlink(temp, dir_fd=fd)
            except FileNotFoundError:
                pass
    return str(root / artist / name)
