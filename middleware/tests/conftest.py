"""Unit/in-process integration tests may never contact external services."""
import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("network disabled in tests; install an explicit transport mock")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.fixture(autouse=True)
def no_index_recheck_pauses(monkeypatch):
    """The import looks a song up again after real pauses; tests that need them set their own."""
    from routes import import_playlist
    monkeypatch.setattr(import_playlist, "INDEX_RECHECK_DELAYS_S", ())
