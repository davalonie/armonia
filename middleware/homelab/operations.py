"""Small bounded reservations; duplicate writes fail instead of waiting forever."""
from contextlib import contextmanager
from threading import Lock

from fastapi import HTTPException

_active = set()
_lock = Lock()


@contextmanager
def reserve(owner, source):
    key = (owner, source)
    with _lock:
        if key in _active:
            raise HTTPException(409, "this recording is already being saved")
        if len(_active) >= 12:
            raise HTTPException(429, "save queue is full")
        _active.add(key)
    try:
        yield
    finally:
        with _lock:
            _active.discard(key)
