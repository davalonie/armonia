"""Mid-song cuts: a check that cannot be answered for a moment is not a revocation.

Simulated providers and fictitious accounts only; no network.
"""
import asyncio
import logging
import sqlite3
import time

import httpx
import pytest
from fastapi import HTTPException

import db
from routes import tracks
from services import session_stream, stream_buffer
from services.preview_stream import UpstreamInfo
from services.session_stream import Observation, guarded


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'armonia.db')
    db.init_db()
    return db.get_session(db.create_session('fixture-user', 's', 't', None, user_id='fixture-id'))


class Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append((record.levelno, record.getMessage()))


@pytest.fixture
def lines():
    handler = Lines()
    session_stream.log.addHandler(handler)
    yield handler.lines
    session_stream.log.removeHandler(handler)


def test_another_writer_holding_the_database_does_not_cut_the_song(session):
    """Regression (reproduced before the fix): a writer holding the lock 0.6 s aborted at block 5/10."""
    received = []

    async def origin():
        for _ in range(10):
            yield b'x' * 1000
            await asyncio.sleep(.1)

    def writer():
        c = sqlite3.connect(db.DB_PATH)
        c.execute('BEGIN EXCLUSIVE')  # Stricter than an import commit: even readers wait.
        time.sleep(.8)
        c.commit()
        c.close()

    async def run():
        async def hold():
            await asyncio.sleep(.25)
            await asyncio.to_thread(writer)
        holder = asyncio.create_task(hold())
        observe = Observation('fixture', 'external', 'tag', 'buffer-hit', 0, 9999)
        async for block in guarded(origin(), session, observe=observe):
            received.append(block)
        await holder
        return observe

    observe = asyncio.run(run())
    assert len(received) == 10 and observe.outcome == 'complete' and observe.soft >= 1


def test_a_database_that_stays_unanswerable_fails_closed(session, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(db, 'check_session', lambda sess: (_ for _ in ()).throw(HTTPException(503, 'busy')))

    async def origin():
        while True:
            clock[0] += .5
            yield b'audio'

    async def run():
        n = 0
        async for _ in guarded(origin(), session, clock=lambda: clock[0]):
            n += 1
        return n

    with pytest.raises(RuntimeError, match='audio transfer interrupted'):
        asyncio.run(run())
    assert clock[0] <= session_stream.LOCAL_GRACE + 1


def test_logout_still_ends_the_transfer_at_the_next_check(session):
    clock, received = [0.0], []

    async def origin():
        for n in range(6):
            if n == 2:
                db.delete_session(session['id'])
            clock[0] += .6
            yield b'audio'

    async def run():
        async for block in guarded(origin(), session, clock=lambda: clock[0]):
            received.append(block)

    with pytest.raises(RuntimeError, match='audio transfer interrupted'):
        asyncio.run(run())
    assert len(received) == 2


@pytest.mark.parametrize('failure', [
    TimeoutError(),
    httpx.ConnectError('navidrome restarting'),
    httpx.HTTPStatusError('busy', request=httpx.Request('GET', 'http://n'), response=httpx.Response(503)),
    ValueError('not json'),
])
def test_a_slow_or_briefly_unreachable_navidrome_does_not_cut_the_song(session, failure):
    clock, checks = [0.0], []

    async def remote():
        checks.append(clock[0])
        if len(checks) in (2, 3):  # Ten seconds without an answer, then it recovers.
            raise failure

    async def origin():
        for _ in range(8):
            clock[0] += 2.5
            yield b'audio'

    async def run():
        return [b async for b in guarded(origin(), session, clock=lambda: clock[0], remote_check=remote)]

    assert len(asyncio.run(run())) == 8 and len(checks) >= 4


def test_an_unverifiable_permission_fails_closed_after_the_grace(session):
    clock = [0.0]

    async def remote():
        raise TimeoutError()

    async def origin():
        while True:
            clock[0] += 2.5
            yield b'audio'

    async def run():
        async for _ in guarded(origin(), session, clock=lambda: clock[0], remote_check=remote):
            pass

    with pytest.raises(RuntimeError, match='audio transfer interrupted'):
        asyncio.run(run())
    assert clock[0] <= session_stream.REMOTE_GRACE + 6


@pytest.mark.parametrize('status', [401, 403, 404])
def test_a_navidrome_denial_still_ends_the_transfer_immediately(session, status):
    clock = [0.0]

    async def remote():
        if clock[0] > 0:
            raise httpx.HTTPStatusError('no', request=httpx.Request('GET', 'http://n'), response=httpx.Response(status))

    async def origin():
        for _ in range(20):
            clock[0] += 1
            yield b'audio'

    async def run():
        return [b async for b in guarded(origin(), session, clock=lambda: clock[0], remote_check=remote)]

    with pytest.raises(RuntimeError):
        asyncio.run(run())


def test_each_audio_response_logs_how_it_ended_without_identifiers(session, lines):
    async def complete():
        yield b'abcd'
        yield b'efgh'

    async def broken():
        yield b'abcd'
        raise httpx.RemoteProtocolError('https://provider.example/audio?signature=secret')

    async def run():
        observe = Observation(session_stream.playback_id(), 'external', session_stream.media_tag('abcdefghijk'),
                              'buffer-fill', 0, 7)
        assert [b async for b in guarded(complete(), session, observe=observe)] == [b'abcd', b'efgh']
        with pytest.raises(RuntimeError):
            async for _ in guarded(broken(), session, observe=Observation('cafe0001', 'external', 'tag', 'relay', 0, 99)):
                pass

        async def endless():
            while True:
                yield b'x'
                await asyncio.sleep(0)

        async def consume():
            async for _ in guarded(endless(), session, observe=Observation('cafe0002', 'library', 'tag', 'navidrome')):
                pass

        listener = asyncio.create_task(consume())
        await asyncio.sleep(.05)
        listener.cancel()
        await asyncio.gather(listener, return_exceptions=True)

    asyncio.run(run())
    text = '\n'.join(message for _, message in lines)
    assert 'sent=8/8' in text and 'outcome=complete' in text
    assert 'outcome=aborted:source-RemoteProtocolError' in text and 'outcome=client-closed' in text
    assert [level for level, m in lines if 'aborted' in m] == [logging.WARNING]
    for secret in ('abcdefghijk', 'signature', 'provider.example', 'fixture-user', 'fixture-id', session['id']):
        assert secret not in text


def test_giving_up_on_preparing_a_song_does_not_cut_it_while_it_plays(monkeypatch):
    """Regression: the prepare timeout cancelled the download shared with the player."""
    monkeypatch.setattr(tracks, '_preparing', {})
    monkeypatch.setattr(tracks, '_prepared_at', {})
    monkeypatch.setattr(stream_buffer, '_songs', {})
    monkeypatch.setattr(tracks.db, 'require_active_session', lambda sess: None)
    monkeypatch.setattr(tracks.sources, 'allowed', lambda *args: None)
    monkeypatch.setattr(tracks, 'PREPARE_TIMEOUT', .2)

    async def resolve(ident):
        return 'https://fixture.googlevideo.com/audio', {}

    async def probe(*args):
        return 'https://fixture.googlevideo.com/audio', UpstreamInfo(total=8, content_type='audio/mp4')

    monkeypatch.setattr(tracks, '_resolve_stream', resolve)
    monkeypatch.setattr(tracks, '_probe', probe)

    async def run():
        gate = asyncio.Event()

        async def slow_provider(client, url, headers, start, end):
            yield b'abcd'[start:]
            await gate.wait()  # Slower than the preparation is willing to wait.
            yield b'efgh'

        monkeypatch.setattr(stream_buffer, 'relay_ranged', slow_provider)
        sess = {'user_id': 'fixture-id', 'username': 'fixture-user'}
        assert (await tracks.prepare_track('abcdefghijk', sess))['state'] == 'preparing'
        await asyncio.sleep(.05)
        song = stream_buffer.get(tracks.owner(sess), 'abcdefghijk')
        async def listen():
            return b''.join([b async for b in song.read(0, 7)])

        listening = asyncio.create_task(asyncio.wait_for(listen(), 5))
        await asyncio.sleep(.05)
        await asyncio.gather(*tracks._preparing.values())  # The preparation times out here.
        assert not song.task.done() and not song.error
        gate.set()
        assert await listening == b'abcdefgh'

    asyncio.run(run())
