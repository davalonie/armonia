"""Exercise the real public-embed parser and matcher together, without network."""
import asyncio
import json

import httpx
import pytest

from homelab import matcher
from homelab.models import Track
from routes import import_playlist
from services import spotify_client


def embed_client(monkeypatch, entries):
    entity = {'name': 'Fixture playlist', 'trackList': entries}
    data = {'props': {'pageProps': {'state': {'data': {'entity': entity}}}}}
    html = '<script id="__NEXT_DATA__">' + json.dumps(data) + '</script>'
    original = httpx.AsyncClient
    def reply(request):
        assert request.url.host == 'open.spotify.com'
        assert request.url.path == '/embed/playlist/fixture'
        return httpx.Response(200, text=html)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(reply), **kw))


@pytest.mark.parametrize('milliseconds,expected', [
    (204118, 204.118), (190926, 190.926), (1000.5, 1.0005), (None, None),
    (0, None), (-1, None), ('204118', None), (True, None),
    (float('nan'), None), (float('inf'), None), (86400001, None),
])
def test_embed_duration_is_validated_and_converted(monkeypatch, milliseconds, expected):
    embed_client(monkeypatch, [{'title': 'Song', 'subtitle': 'Artist', 'duration': milliseconds}])
    result = asyncio.run(spotify_client.fetch_playlist('spotify:playlist:fixture'))
    assert result['tracks'][0]['duration'] == expected


def test_missing_duration_stays_unverified(monkeypatch):
    embed_client(monkeypatch, [{'title': 'Song', 'subtitle': 'Artist'}])
    wanted = asyncio.run(spotify_client.fetch_playlist('spotify:playlist:fixture'))['tracks'][0]
    candidate = Track(source='youtube', source_id='abcdefghijk', title='Song', artist='Artist', duration=200)
    result = matcher.rank(wanted, [candidate])
    assert result['selected'] is None
    assert 'duration unverified' in result['candidates'][0]['reasons']


@pytest.mark.parametrize('candidate_title,candidate_duration,downloaded', [
    ('Song', 204, True), ('Song Live', 204, False), ('Song', 250, False),
])
def test_embed_to_import_matches_recording_and_preserves_order(monkeypatch, candidate_title, candidate_duration, downloaded):
    embed_client(monkeypatch, [{'title': 'Song', 'subtitle': 'Artist', 'duration': 204118}])
    playlist = asyncio.run(spotify_client.fetch_playlist('spotify:playlist:fixture'))
    job = import_playlist.ImportJob('fixture-job', playlist['name'], 1, username='nd:alice')
    monkeypatch.setattr(import_playlist, '_imports', {job.import_id: job})
    monkeypatch.setattr(import_playlist.db, 'require_active_session', lambda _: None)
    monkeypatch.setenv('MUSIC_YOUTUBE_CAPABILITIES', 'persist')
    monkeypatch.delenv('MUSIC_SOURCES_FILE', raising=False)
    saved = []
    created = []
    async def find(*args):
        return 'local-song' if saved else None
    async def download(video, artist, title, *args, **options):
        saved.append((video, artist, title))
        return '/fixture/audio.m4a'
    async def scan(*args):
        pass
    async def create(name, ids, *args):
        created.append((name, ids))
        return 'playlist-id'
    monkeypatch.setattr(import_playlist.navidrome_client, 'find_song_id', find)
    monkeypatch.setattr(import_playlist.navidrome_client, 'trigger_scan_and_wait', scan)
    monkeypatch.setattr(import_playlist.navidrome_client, 'create_playlist', create)
    monkeypatch.setattr(import_playlist, '_download_with_retry', download)
    monkeypatch.setattr(import_playlist.ytdlp_service, 'search', lambda *a, **kw: [
        {'videoId': 'abcdefghijk', 'title': candidate_title, 'channel': 'Artist', 'duration': candidate_duration}])
    asyncio.run(import_playlist._run_import(job.import_id, playlist['tracks'], 'alice', 'salt', 'token', '/fixture', 1, {}))
    assert job.status == 'done'
    assert job.downloaded == int(downloaded)
    assert job.failed == int(not downloaded)
    assert saved == ([('abcdefghijk', 'Artist', 'Song')] if downloaded else [])
    assert created == ([('Fixture playlist', ['local-song'])] if downloaded else [])
