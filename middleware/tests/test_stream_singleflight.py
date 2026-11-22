import asyncio
import time

from routes import tracks
from services.preview_stream import StreamInfoCache


def test_cold_range_requests_share_resolution_and_warm_cache(monkeypatch):
    monkeypatch.setattr(tracks, '_stream_info_cache', StreamInfoCache())
    monkeypatch.setattr(tracks, '_stream_resolvers', {})
    monkeypatch.setattr(tracks, '_resolution_slots', asyncio.Semaphore(2))
    calls = []
    def extract(ident):
        calls.append(ident)
        time.sleep(.03)
        return 'https://fixture.googlevideo.com/audio', {}
    monkeypatch.setattr(tracks, 'get_stream_info', extract)
    async def run():
        results = await asyncio.gather(*(tracks._resolve_stream('abcdefghijk') for _ in range(8)))
        assert len(results) == 8
        await tracks._resolve_stream('abcdefghijk')
    asyncio.run(run())
    assert calls == ['abcdefghijk']


def test_disconnect_does_not_cancel_other_waiters(monkeypatch):
    monkeypatch.setattr(tracks, '_stream_info_cache', StreamInfoCache())
    monkeypatch.setattr(tracks, '_stream_resolvers', {})
    monkeypatch.setattr(tracks, '_resolution_slots', asyncio.Semaphore(2))
    monkeypatch.setattr(tracks, 'get_stream_info', lambda _: (time.sleep(.03) or ('https://fixture.googlevideo.com/audio', {})))
    async def run():
        first=asyncio.create_task(tracks._resolve_stream('abcdefghijk'))
        second=asyncio.create_task(tracks._resolve_stream('abcdefghijk'))
        await asyncio.sleep(.005)
        first.cancel()
        await asyncio.gather(first,return_exceptions=True)
        assert (await second)[0].startswith('https://')
    asyncio.run(run())


def test_prepare_resolves_once_and_buffers_the_song_privately_per_user(monkeypatch):
    import pytest
    from fastapi import HTTPException

    monkeypatch.setattr(tracks, '_stream_info_cache', StreamInfoCache())
    monkeypatch.setattr(tracks, '_stream_resolvers', {})
    monkeypatch.setattr(tracks, '_resolution_slots', asyncio.Semaphore(2))
    monkeypatch.setattr(tracks, '_preparing', {})
    monkeypatch.setattr(tracks, '_prepared_at', {})
    monkeypatch.setenv('MUSIC_YOUTUBE_CAPABILITIES', 'stream')
    monkeypatch.delenv('MUSIC_SOURCES_FILE', raising=False)
    calls = []
    def extract(ident):
        calls.append(ident)
        time.sleep(.03)
        if ident == 'failfailfai':
            raise RuntimeError('provider down')
        return f'https://fixture.googlevideo.com/audio?expire={int(time.time() + 6 * 3600)}', {}
    monkeypatch.setattr(tracks, 'get_stream_info', extract)
    from services import preview_stream, stream_buffer
    fetched = []
    async def probe(client, url, headers, video_id):
        return url, preview_stream.UpstreamInfo(total=5, content_type='audio/mp4')
    async def relay(client, url, headers, start, end):
        fetched.append(url)
        yield b'audio'
    monkeypatch.setattr(tracks, '_probe', probe)
    monkeypatch.setattr(stream_buffer, 'relay_ranged', relay)
    monkeypatch.setattr(stream_buffer, '_songs', {})
    monkeypatch.setattr(tracks.db, 'require_active_session', lambda sess: None)
    alice, bob = {'user_id': 'alice', 'username': 'alice'}, {'user_id': 'bob', 'username': 'bob'}
    async def run():
        assert (await tracks.prepare_track('abcdefghijk', alice))['state'] == 'preparing'
        # One in flight per user: a second song is skipped, another user is not blocked.
        assert (await tracks.prepare_track('second_song', alice))['state'] == 'skipped'
        assert (await tracks.prepare_track('abcdefghijk', bob))['state'] == 'preparing'
        await asyncio.gather(*tracks._preparing.values())
        assert calls == ['abcdefghijk']  # Both users shared one resolution.
        await asyncio.gather(*[s.task for s in stream_buffer._songs.values()])
        assert (await tracks.prepare_track('abcdefghijk', alice))['state'] == 'ready'
        # Each user holds a private copy of the prepared song; neither is a listen.
        assert len(fetched) == 2 and bytes(stream_buffer.get(tracks.owner(alice), 'abcdefghijk').data) == b'audio'
        # Pressing play now finds the source resolved.
        await tracks._resolve_stream('abcdefghijk')
        assert calls == ['abcdefghijk']
        # A provider failure while preparing is silent; playback reports it later.
        assert (await tracks.prepare_track('failfailfai', alice))['state'] == 'preparing'
        await asyncio.gather(*tracks._preparing.values())
        assert not tracks._preparing
        with pytest.raises(HTTPException):
            await tracks.prepare_track('not valid', alice)
        tracks._prepared_at['alice'] = [time.monotonic()] * 12
        assert (await tracks.prepare_track('third_song1', alice))['state'] == 'skipped'
    asyncio.run(run())


def test_prepare_needs_stream_permission(monkeypatch):
    import pytest
    from fastapi import HTTPException

    monkeypatch.setenv('MUSIC_YOUTUBE_CAPABILITIES', '')
    monkeypatch.delenv('MUSIC_SOURCES_FILE', raising=False)
    monkeypatch.setattr(tracks.db, 'require_active_session', lambda sess: None)
    with pytest.raises(HTTPException):
        asyncio.run(tracks.prepare_track('abcdefghijk', {'user_id': 'alice', 'username': 'alice'}))


def test_prepare_holds_slot_during_fill_and_cancellation_stops_download(monkeypatch):
    from services import stream_buffer
    from services.preview_stream import UpstreamInfo

    monkeypatch.setattr(tracks, '_preparing', {})
    monkeypatch.setattr(tracks, '_prepared_at', {})
    monkeypatch.setattr(stream_buffer, '_songs', {})
    monkeypatch.setattr(tracks.db, 'require_active_session', lambda sess: None)
    monkeypatch.setattr(tracks.sources, 'allowed', lambda *args: None)

    async def resolve(ident):
        return 'https://fixture.googlevideo.com/audio', {}

    async def probe(*args):
        return 'https://fixture.googlevideo.com/audio', UpstreamInfo(total=5, content_type='audio/mp4')

    monkeypatch.setattr(tracks, '_resolve_stream', resolve)
    monkeypatch.setattr(tracks, '_probe', probe)

    async def run():
        started, gate = asyncio.Event(), asyncio.Event()

        async def relay(*args):
            started.set()
            await gate.wait()
            yield b'audio'

        monkeypatch.setattr(stream_buffer, 'relay_ranged', relay)
        sess = {'user_id': 'alice', 'username': 'alice'}
        assert (await tracks.prepare_track('abcdefghijk', sess))['state'] == 'preparing'
        await asyncio.wait_for(started.wait(), 2)
        song = stream_buffer.get(tracks.owner(sess), 'abcdefghijk')
        assert not song.complete
        assert (await tracks.prepare_track('abcdefghijk', sess))['state'] == 'preparing'
        assert (await tracks.prepare_track('second_song', sess))['state'] == 'skipped'
        worker = tracks._preparing[tracks.owner(sess)]
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        assert song.task.cancelled()
        assert stream_buffer.get(tracks.owner(sess), 'abcdefghijk') is None
        assert not tracks._preparing

    asyncio.run(run())


def test_prepare_rechecks_session_and_policy_after_probe(monkeypatch):
    from fastapi import HTTPException

    from services import stream_buffer
    from services.preview_stream import UpstreamInfo

    monkeypatch.setattr(tracks, '_preparing', {})
    monkeypatch.setattr(tracks, '_prepared_at', {})
    monkeypatch.setattr(stream_buffer, '_songs', {})
    state = {'session': True, 'policy': True, 'revoke': None}

    def active(sess):
        if not state['session']:
            raise HTTPException(401, 'revoked')

    def allowed(*args):
        if not state['policy']:
            raise HTTPException(403, 'revoked')

    async def resolve(ident):
        return 'https://fixture.googlevideo.com/audio', {}

    async def probe(*args):
        state[state['revoke']] = False
        return 'https://fixture.googlevideo.com/audio', UpstreamInfo(total=5, content_type='audio/mp4')

    monkeypatch.setattr(tracks.db, 'require_active_session', active)
    monkeypatch.setattr(tracks.sources, 'allowed', allowed)
    monkeypatch.setattr(tracks, '_resolve_stream', resolve)
    monkeypatch.setattr(tracks, '_probe', probe)

    async def run():
        for key in ('session', 'policy'):
            state.update(session=True, policy=True, revoke=key)
            await tracks.prepare_track('abcdefghijk', {'user_id': 'alice', 'username': 'alice'})
            await asyncio.gather(*tracks._preparing.values())
            assert not stream_buffer._songs

    asyncio.run(run())


def test_resolved_location_is_reused_until_shortly_before_the_provider_expiry():
    cache = StreamInfoCache()
    now = 1_000_000
    assert cache.lifetime('https://x.googlevideo.com/a', now=lambda: now) == 30 * 60
    assert cache.lifetime(f'https://x.googlevideo.com/a?expire={now + 6 * 3600}', now=lambda: now) == 3 * 3600
    assert cache.lifetime(f'https://x.googlevideo.com/a?expire={now + 3600}', now=lambda: now) == 3000
    assert cache.lifetime(f'https://x.googlevideo.com/a?expire={now - 5}', now=lambda: now) == 60
    assert cache.lifetime('https://x.googlevideo.com/a?expire=soon', now=lambda: now) == 30 * 60
