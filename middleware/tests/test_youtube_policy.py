"""Provider opt-in must not widen URL access or override recording denials."""
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from auth import get_current_session
from homelab import sources
from routes import sources as routes


@pytest.fixture(autouse=True)
def policy_env(monkeypatch):
    monkeypatch.delenv('MUSIC_SOURCES_FILE', raising=False)
    monkeypatch.delenv('MUSIC_YOUTUBE_CAPABILITIES', raising=False)


def test_default_denies_youtube():
    with pytest.raises(HTTPException) as error:
        sources.allowed('youtube', 'abcdefghijk', 'stream')
    assert error.value.status_code == 403


@pytest.mark.parametrize('cap', ['stream', 'offline', 'persist'])
def test_provider_opt_in_is_capability_specific(monkeypatch, cap):
    monkeypatch.setenv('MUSIC_YOUTUBE_CAPABILITIES', cap)
    assert sources.allowed('youtube', 'abcdefghijk', cap)[cap] is True
    for other in {'stream', 'offline', 'persist', 'cache'} - {cap}:
        with pytest.raises(HTTPException):
            sources.allowed('youtube', 'abcdefghijk', other)


@pytest.mark.parametrize('source,key', [
    ('authorized_http', 'abcdefghijk'), ('youtube_music', 'abcdefghijk'),
    ('youtube', 'https://localhost'), ('youtube', '../abcdefghijk'),
    ('youtube', 'abcdefghijk\n'), ('youtube', '*'),
])
def test_opt_in_does_not_allow_urls_or_other_providers(monkeypatch, source, key):
    monkeypatch.setenv('MUSIC_YOUTUBE_CAPABILITIES', 'stream,offline,persist')
    with pytest.raises(HTTPException):
        sources.allowed(source, key, 'stream')


def test_explicit_record_overrides_provider_and_does_not_pollute_discovery(monkeypatch, tmp_path):
    monkeypatch.setenv('MUSIC_YOUTUBE_CAPABILITIES', 'stream,offline,persist')
    path = tmp_path / 'sources.json'
    path.write_text(json.dumps({'youtube:abcdefghijk': {'authorization': 'admin', 'stream': False}}))
    monkeypatch.setenv('MUSIC_SOURCES_FILE', str(path))
    for cap in ('stream', 'persist', 'offline'):
        with pytest.raises(HTTPException):
            sources.allowed('youtube', 'abcdefghijk', cap)
    assert sources.public_tracks() == []


def test_capabilities_agree_with_enforcement(monkeypatch):
    monkeypatch.setenv('MUSIC_YOUTUBE_CAPABILITIES', 'stream,offline,persist')
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_session] = lambda: {'username': 'fixture'}
    with TestClient(app) as client:
        assert client.get('/api/sources/youtube/abcdefghijk/capabilities').json() == {
            'stream': True, 'offline': True, 'persist': True, 'cache': False}
        assert not any(client.get('/api/sources/authorized_http/abcdefghijk/capabilities').json().values())
