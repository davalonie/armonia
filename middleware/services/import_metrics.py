"""Per-import stage durations. No URLs, credentials or listening history."""

from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter

sink = ContextVar("import_metrics", default=None)


def event(stage, seconds):
    callback = sink.get()
    if callback:
        callback(stage, seconds)


@contextmanager
def measure(stage):
    start = perf_counter()
    try:
        yield
    finally:
        event(stage, perf_counter() - start)
