import asyncio
import json
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import db
from auth import get_current_session
from homelab import audio_cache, listening, store
from routes import sources as source_routes
from routes import tracks


@pytest.fixture
def auth_session(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sessions.db")
    db.init_db()
    store.init()
    sid = db.create_session("alice", "s", "t", str(tmp_path / "music"), library_id=2, user_id="alice")
    return db.get_session(sid)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    folder = tmp_path / 'cache'
    music = tmp_path / 'music'
    music.mkdir()
    monkeypatch.setenv('MUSIC_CACHE_DIR', str(folder))
    monkeypatch.setenv('MUSIC_CACHE_MAX_BYTES', '100')
    monkeypatch.setattr(audio_cache, 'MUSIC_DIR', str(music))
    return folder, music


def test_cache_reuses_source_but_separates_users_and_urls(cache, monkeypatch):
    calls = []
    async def fetch(url, maximum):
        calls.append(url)
        return b'fixture', 'audio/mpeg'
    monkeypatch.setattr(audio_cache, 'fetch', fetch)
    async def run():
        await audio_cache.get('alice', 'track', 'https://source/a')
        await audio_cache.get('alice', 'track', 'https://source/a')
        await audio_cache.get('bob', 'track', 'https://source/a')
        await audio_cache.get('alice', 'track', 'https://source/b')
    asyncio.run(run())
    assert len(calls) == 3
    assert len(list(cache[0].glob('*.audio'))) == 3
    assert not list(cache[1].iterdir())


def test_cache_ttl_quota_and_lru_do_not_touch_library(cache, monkeypatch):
    async def fetch(url, maximum):
        return url.encode() * 10, 'audio/mpeg'
    monkeypatch.setattr(audio_cache, 'fetch', fetch)
    async def run():
        await audio_cache.get('alice', 'a', 'aaaaa')
        await audio_cache.get('alice', 'b', 'bbbbb')
        await audio_cache.get('alice', 'a', 'aaaaa')
        await audio_cache.get('alice', 'c', 'ccccc')
    asyncio.run(run())
    data = [f.read_bytes() for f in cache[0].glob('*.audio')]
    assert data and b'b' * 50 not in data and sum(map(len, data)) <= 100
    keep = cache[1] / 'permanent.mp3'
    keep.write_bytes(b'permanent')
    for f in cache[0].glob('*.json'):
        value = json.loads(f.read_text())
        value['expires'] = time.time() - 1
        f.write_text(json.dumps(value))
    audio_cache.cleanup()
    assert not list(cache[0].glob('*.audio')) and keep.read_bytes() == b'permanent'


def test_cache_cannot_be_library_and_never_follows_links(cache, monkeypatch, tmp_path):
    monkeypatch.setenv('MUSIC_CACHE_DIR', str(cache[1]))
    with pytest.raises(RuntimeError):
        audio_cache.root()
    monkeypatch.setenv('MUSIC_CACHE_DIR', str(cache[0]))
    audio_cache.root()
    outside = tmp_path / 'document'
    outside.write_bytes(b'not audio')
    (cache[0] / ('a' * 64 + '.audio')).symlink_to(outside)
    audio_cache.cleanup()
    assert outside.read_bytes() == b'not audio'
    assert not (cache[0] / ('a' * 64 + '.audio')).exists()


def test_oversized_tracks_do_not_fill_cache(cache, monkeypatch):
    async def fetch(url, maximum):
        raise audio_cache.TooLarge()
    monkeypatch.setattr(audio_cache, 'fetch', fetch)
    assert asyncio.run(audio_cache.get('a', 'a', 'https://source')) is None
    assert not list(cache[0].iterdir())


def test_cleanup_removes_crash_temporary_files_and_orphan_metadata(cache):
    folder = audio_cache.root()
    (folder / (".cache-" + "a" * 32)).write_bytes(b"crash")
    (folder / ("a" * 64 + ".json")).write_bytes(b"{}")
    audio_cache.cleanup()
    assert not list(folder.iterdir())


def test_external_range_and_revoked_permission_are_enforced(cache, tmp_path, monkeypatch, auth_session):
    catalog = tmp_path / 'sources.json'
    record = {'authorization': 'own synthetic sound', 'stream': True, 'offline': False, 'cache': True,
              'url': 'https://fixture/audio', 'metadata': {'title': 'Fixture', 'artist': 'Fixture'}}
    catalog.write_text(json.dumps({'authorized_http:fixture': record}))
    monkeypatch.setenv('MUSIC_SOURCES_FILE', str(catalog))
    async def fetch(url, maximum):
        return b'0123456789', 'audio/mpeg'
    monkeypatch.setattr(audio_cache, 'fetch', fetch)
    app = FastAPI()
    app.include_router(tracks.router)
    app.include_router(source_routes.router)
    app.dependency_overrides[get_current_session] = lambda: auth_session
    c = TestClient(app)
    r = c.get('/api/external/fixture', headers={'Range': 'bytes=2-4'})
    assert r.status_code == 206 and r.content == b'234' and r.headers['Content-Range'] == 'bytes 2-4/10'
    assert c.get('/api/external/fixture?purpose=offline').status_code == 403
    assert c.get('/api/sources/authorized_http/fixture/capabilities').json()['offline'] is False
    record['stream'] = False
    catalog.write_text(json.dumps({'authorized_http:fixture': record}))
    assert c.get('/api/external/fixture').status_code == 403
    assert c.post('/api/sources/fixture/save').status_code == 403


def test_fetch_never_follows_redirect_or_accepts_non_audio(monkeypatch):
    original = httpx.AsyncClient
    for response in (httpx.Response(302, headers={'Location': 'http://private/'}),
                     httpx.Response(200, headers={'Content-Type': 'text/html'}, content=b'html')):
        monkeypatch.setattr(httpx, 'AsyncClient', lambda response=response, **kw: original(transport=httpx.MockTransport(lambda _: response), **kw))
        with pytest.raises(Exception) as error:
            asyncio.run(audio_cache.fetch('https://source/', 100))
        assert getattr(error.value, 'status_code', None) == 502


def test_artist_identifiers_are_forwarded_to_private_koito():
    event = {'started_at': 100, 'track': {'artist': 'Fixture', 'title': 'Song', 'artist_mbids': ['11111111-1111-4111-8111-111111111111']}}
    assert listening.payload(event)['payload'][0]['track_metadata']['additional_info']['artist_mbids'] == event['track']['artist_mbids']


def test_saved_does_not_mean_indexed_and_existing_recordings_not_duplicated(cache, tmp_path, monkeypatch, auth_session):
    from mutagen.id3 import ID3

    from services import safe_files
    monkeypatch.setattr(safe_files, 'MUSIC_DIR', str(cache[1]))
    monkeypatch.setenv('MUSIC_FREE_SPACE_RESERVE_BYTES', '0')
    record = {'authorization': 'test', 'persist': True, 'url': 'https://fixture/audio',
              'metadata': {'artist': 'Fixture', 'title': 'Song', 'artist_mbids': ['11111111-1111-4111-8111-111111111111']}}
    path = tmp_path / 'sources.json'
    path.write_text(json.dumps({'authorized_http:fixture': record}))
    monkeypatch.setenv('MUSIC_SOURCES_FILE', str(path))
    async def fetch(*args):
        return b'simulated audio', 'audio/mpeg'
    class Process:
        async def wait(self):
            return 0
    async def run(*args, **kw):
        ID3().save(args[-1])
        return Process()
    async def known(*args):
        return set()
    async def scan(*args, **kw):
        return False
    async def library(*args):
        return 2
    monkeypatch.setattr(audio_cache, 'fetch', fetch)
    monkeypatch.setattr(source_routes.asyncio, 'create_subprocess_exec', run)
    monkeypatch.setattr(source_routes.tagger_service, 'tag', lambda *args: None)
    monkeypatch.setattr(source_routes.navidrome_client, 'matching_song_ids', known)
    monkeypatch.setattr(source_routes.navidrome_client, 'scan_until', scan)
    monkeypatch.setattr(source_routes.navidrome_client, 'require_library_access', library)
    app = FastAPI()
    app.include_router(source_routes.router)
    app.dependency_overrides[get_current_session] = lambda: auth_session
    c = TestClient(app)
    assert c.post('/api/sources/fixture/save').json() == {'saved': True, 'indexed': False}
    saved = list(cache[1].rglob('*.mp3'))
    assert len(saved) == 1 and 'MusicBrainz Artist Id' in str(ID3(saved[0]))
    async def duplicate(*args):
        return {'existing'}
    monkeypatch.setattr(source_routes.navidrome_client, 'matching_song_ids', duplicate)
    assert c.post('/api/sources/fixture/save').status_code == 409
    assert len(list(cache[1].rglob('*.mp3'))) == 1
