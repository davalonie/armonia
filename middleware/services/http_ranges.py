"""Only a bounded single byte range reaches downstream media servers."""
import re

from fastapi import HTTPException


def single_range(value):
    if value is None:
        return None
    match = re.fullmatch(r"bytes=([0-9]{0,19})-([0-9]{0,19})", value)
    if not match or not any(match.groups()):
        raise HTTPException(416, "one valid byte range is required")
    start, end = (int(x) if x else None for x in match.groups())
    if any(x is not None and x > 2**63 - 1 for x in (start, end)):
        raise HTTPException(416, "byte range exceeds limit")
    if (start is not None and end is not None and start > end) or (start is None and end == 0):
        raise HTTPException(416, "invalid byte range")
    return value
