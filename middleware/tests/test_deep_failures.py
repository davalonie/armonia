"""Concurrency, interruption and revocation regressions with private fixtures."""
import asyncio
import errno
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

import db
import jobs
from homelab import audio_cache, integrations, listening, operations, store
from homelab.models import PlaylistWrite, Track
from services import safe_files
from services.preview_stream import StreamInfoCache, parse_range, relay_ranged
from services.session_stream import guarded


@pytest.fixture
def private(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'armonia.db')
    db.init_db()
    store.init()
    jobs._jobs.clear()
    jobs._active_video_ids.clear()
    jobs._cancelled.clear()
    sid = db.create_session('alice', 's', 't', str(tmp_path / 'music'), library_id=7, user_id='alice-id')
    return db.get_session(sid)


def test_same_user_duplicate_reservation_is_atomic_but_users_are_independent(private):
    gate = Barrier(8)
    def create(_):
        gate.wait()
        try:
            return jobs.create_job('abcdefghijk', 'A', 'T', 'alice-id')
        except HTTPException as e:
            return e.status_code
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(create, range(8)))
    assert results.count(409) == 7
    other = jobs.create_job('abcdefghijk', 'A', 'T', 'bob-id')
    jobs.update_job(other.job_id, status='done')
    assert jobs.is_video_active('abcdefghijk', 'alice-id')
    assert not jobs.is_video_active('abcdefghijk', 'bob-id')


def test_failed_job_persistence_releases_reservation(private, monkeypatch):
    def full(*a, **kw):
        raise sqlite3.OperationalError('disk full')
    monkeypatch.setattr(db, 'upsert_download', full)
    with pytest.raises(sqlite3.OperationalError):
        jobs.create_job('abcdefghijk', 'A', 'T', 'alice-id')
    assert not jobs._active_video_ids and not jobs._jobs


def test_job_queue_is_bounded_and_capacity_recovers(private):
    active = [jobs.create_job(f'fixture{i:04}', 'A', 'T', 'alice-id') for i in range(5)]
    with pytest.raises(HTTPException) as error:
        jobs.create_job('another0000', 'A', 'T', 'alice-id')
    assert error.value.status_code == 429
    jobs.update_job(active[0].job_id, status='error')
    assert jobs.create_job('another0000', 'A', 'T', 'alice-id')


def test_cancellation_is_not_overwritten_by_late_status_persistence(private, monkeypatch):
    job = jobs.create_job('abcdefghijk', 'A', 'T', 'alice-id')
    started, release = Event(), Event()
    original = db.upsert_download
    def pause(*args, **kw):
        if args[4] == 'downloading':
            started.set()
            assert release.wait(2)
        return original(*args, **kw)
    monkeypatch.setattr(db, 'upsert_download', pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        updating = pool.submit(jobs.update_job, job.job_id, status='downloading')
        assert started.wait(1)
        cancelling = pool.submit(jobs.cancel_job, job.job_id)
        release.set()
        updating.result()
        assert cancelling.result()
    assert jobs.get_job(job.job_id).status == 'cancelled'
    assert db.get_download_record(job.job_id)['status'] == 'cancelled'


def test_interrupt_restarts_as_error_without_modifying_library(private):
    job = jobs.create_job('abcdefghijk', 'A', 'T', 'alice-id')
    jobs.update_job(job.job_id, status='downloading')
    db.init_db()
    assert db.get_download_record(job.job_id)['status'] == 'error'
    assert db.get_download_record(job.job_id)['error'] == 'interrupted by restart'


@pytest.mark.parametrize('indexed', [False, True])
def test_retry_after_publication_cannot_download_again(private, tmp_path, monkeypatch, indexed):
    from fastapi import BackgroundTasks

    from routes import download
    music = tmp_path / 'music'
    music.mkdir()
    monkeypatch.setattr(safe_files, 'MUSIC_DIR', str(music))
    published = music / 'fixture.mp3'
    published.write_bytes(b'complete audio')
    db.upsert_download('old', 'abcdefghijk', 'Fixture', 'Tone', 'error', username='nd:alice-id',
                       file_path=None if indexed else str(published))
    async def grant(sess):
        return 7
    async def duplicate(*args):
        return indexed
    monkeypatch.setattr(download.navidrome_client, 'require_library_access', grant)
    monkeypatch.setattr(download.sources, 'allowed', lambda *a: {})
    monkeypatch.setattr(download, '_is_duplicate', duplicate)
    tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as error:
        asyncio.run(download.retry_download('old', tasks, private))
    assert error.value.status_code == 409
    assert not tasks.tasks and not jobs._jobs
    assert db.get_download_record('old') and published.read_bytes() == b'complete audio'


def test_retry_publication_check_rejects_symlinks_and_foreign_paths(tmp_path):
    root = tmp_path / 'music'
    root.mkdir()
    private = tmp_path / 'private'
    private.write_bytes(b'never read')
    (root / 'link.mp3').symlink_to(private)
    for path in (str(private), 'link.mp3', '../private'):
        with pytest.raises(ValueError):
            safe_files.private_file_exists(root, path)
    assert not safe_files.private_file_exists(root, 'missing.mp3')
    assert private.read_bytes() == b'never read'


def test_source_reservation_is_released_after_failure():
    with pytest.raises(RuntimeError):
        with operations.reserve('alice', 'one'):
            with pytest.raises(HTTPException):
                with operations.reserve('alice', 'one'):
                    pass
            with operations.reserve('bob', 'one'):
                pass
            raise RuntimeError('source disconnected')
    with operations.reserve('alice', 'one'):
        pass


def test_logout_during_copy_prevents_final_publication(private, tmp_path, monkeypatch):
    music = tmp_path / 'music'
    music.mkdir()
    staged = tmp_path / 'stage.mp3'
    staged.write_bytes(b'fictional audio')
    copy = safe_files.shutil.copyfileobj
    def revoke(src, dst):
        copy(src, dst)
        db.delete_session(private['id'])
    monkeypatch.setattr(safe_files.shutil, 'copyfileobj', revoke)
    with pytest.raises(HTTPException) as error:
        safe_files.publish(staged, music, 'Artist', 'Title', final_guard=lambda: db.active_session(private))
    assert error.value.status_code == 401
    assert not [p for p in music.rglob('*') if p.is_file()]


def test_expired_session_cannot_publish_or_renew(private):
    with sqlite3.connect(db.DB_PATH) as c:
        c.execute('UPDATE sessions SET expires_at=1')
    with pytest.raises(HTTPException) as error:
        db.require_active_session(private)
    assert error.value.status_code == 401
    with sqlite3.connect(db.DB_PATH) as c:
        assert c.execute('SELECT expires_at FROM sessions').fetchone()[0] == 1


@pytest.mark.parametrize('during_copy', [True, False])
def test_job_cancellation_during_publication_is_ordered_and_retains_committed_path(private, tmp_path, monkeypatch, during_copy):
    from routes import download
    music = tmp_path / 'music'
    music.mkdir()
    staged = tmp_path / 'fixture.mp3'
    staged.write_bytes(b'fixture audio')
    job = jobs.create_job('abcdefghijk', 'Fixture', 'Tone', 'nd:alice-id')
    copy = safe_files.shutil.copyfileobj
    def copying(src, dst):
        copy(src, dst)
        if during_copy:
            jobs.cancel_job(job.job_id)
    monkeypatch.setattr(safe_files.shutil, 'copyfileobj', copying)
    async def save(*args, **kwargs):
        path = await safe_files.run_blocking(safe_files.publish, staged, music, 'Fixture', 'Tone', final_guard=kwargs['final_guard'], record_intent=kwargs['record_intent'])
        if not during_copy:
            jobs.cancel_job(job.job_id)
        return path
    monkeypatch.setattr(download.ytdlp_service, 'download_limited', save)
    asyncio.run(download._run_download(job.job_id, job.video_id, job.artist, job.title,
                private['username'], private['salt'], private['token'], str(music), session=private))
    record = db.get_download_record(job.job_id)
    assert record['status'] == 'cancelled'
    published = [p for p in music.rglob('*') if p.is_file()]
    if during_copy:
        assert not published and record['file_path'] and not Path(record['file_path']).exists()
    else:
        assert len(published) == 1 and record['file_path'] == str(published[0])
        assert published[0].read_bytes() == b'fixture audio'


def test_existing_stream_stops_and_closes_upstream_after_logout(private):
    closed, received = [], []
    clock = [0.0]
    async def origin():
        try:
            yield b'before'
            db.delete_session(private['id'])
            clock[0] = 1
            yield b'after'
        finally:
            closed.append(True)
    async def run():
        async for part in guarded(origin(), private, clock=lambda: clock[0]):
            received.append(part)
    with pytest.raises(RuntimeError, match='audio transfer interrupted'):
        asyncio.run(run())
    assert received == [b'before']
    assert closed == [True]


def test_session_revoked_during_remote_grant_check_is_denied(private, monkeypatch):
    from services import navidrome_client
    def response(request):
        db.delete_session(private['id'])
        return httpx.Response(200, json={'subsonic-response': {'status':'ok', 'musicFolders': {'musicFolder': [{'id':7}]}}})
    original = httpx.AsyncClient
    monkeypatch.setattr(navidrome_client.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(response), **kw))
    with pytest.raises(HTTPException) as error:
        asyncio.run(navidrome_client.require_library_access(private))
    assert error.value.status_code == 401


def test_remote_track_permission_is_rechecked_without_a_local_logout(private):
    clock, checks, closed, received = [0.0], [], [], []
    async def remote():
        checks.append(clock[0])
        if len(checks) == 2:
            raise HTTPException(403, 'library grant withdrawn')
    async def origin():
        try:
            for moment in (0, 1, 4, 5, 6):
                clock[0] = moment
                yield b'audio'
        finally:
            closed.append(True)
    async def run():
        async for part in guarded(origin(), private, clock=lambda:clock[0], remote_check=remote):
            received.append(part)
    with pytest.raises(RuntimeError, match='audio transfer interrupted'):
        asyncio.run(run())
    assert len(received) == 3
    assert checks == [0, 5] and closed == [True]
    db.require_active_session(private)  # Only the upstream permission was withdrawn.


def test_broken_stream_aborts_without_exposing_provider_url(private):
    closed = []
    async def origin():
        try:
            yield b'first block'
            raise httpx.ReadError('https://provider/audio?credential=private')
        finally:
            closed.append(True)
    async def run():
        return [part async for part in guarded(origin(), private)]
    with pytest.raises(RuntimeError, match='audio transfer interrupted') as error:
        asyncio.run(run())
    assert error.value.__suppress_context__ and closed == [True]


def test_cancelled_stream_closes_its_origin(private):
    async def run():
        entered, closed = asyncio.Event(), []
        async def origin():
            try:
                yield b'audio'
                entered.set()
                await asyncio.Event().wait()
            finally:
                closed.append(True)
        async def consume():
            return [part async for part in guarded(origin(), private)]
        task = asyncio.create_task(consume())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed == [True]
    asyncio.run(run())


@pytest.mark.parametrize('allowed', [True, False])
def test_native_stream_validates_specific_song_and_closes_transport(private, monkeypatch, allowed):
    from starlette.requests import Request

    from routes import stream
    closed, calls = [], []
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'fixture audio'
        async def aclose(self):
            closed.append(True)
    def response(request):
        calls.append(request)
        if request.url.path.endswith('/stream'):
            return httpx.Response(200, stream=Body())
        assert request.url.path.endswith('/getSong')
        assert request.url.params['id'] == 'fixture-song'
        assert request.url.params['u'] == private['username']
        data = {'status': 'ok', 'song': {'id':'fixture-song'}} if allowed else {'status': 'failed'}
        return httpx.Response(200, json={'subsonic-response': data})
    original = httpx.AsyncClient
    monkeypatch.setattr(stream.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(response), **kw))
    async def run():
        result = await stream.stream('fixture-song', Request({'type':'http', 'headers': []}), private)
        return [part async for part in result.body_iterator]
    if allowed:
        assert asyncio.run(run()) == [b'fixture audio']
        assert len(calls) == 2 and closed == [True]
    else:
        with pytest.raises(HTTPException) as error:
            asyncio.run(run())
        assert error.value.status_code == 403
        assert len(calls) == 1 and not closed  # No audio request was opened.


def test_partial_disk_write_leaves_no_published_or_hidden_file(tmp_path, monkeypatch):
    root = tmp_path / 'music'
    root.mkdir()
    staged = tmp_path / 'stage.mp3'
    staged.write_bytes(b'original audio')
    def full(src, dst):
        dst.write(b'partial')
        raise OSError(errno.ENOSPC, 'simulated disk full')
    monkeypatch.setattr(safe_files.shutil, 'copyfileobj', full)
    with pytest.raises(OSError):
        safe_files.publish(staged, root, 'Artist', 'Title')
    assert not [p for p in root.rglob('*') if p.is_file()]
    assert staged.read_bytes() == b'original audio'


def test_unlink_during_open_playback_does_not_corrupt_reader(tmp_path):
    audio = tmp_path / 'audio.mp3'
    audio.write_bytes(b'fixture original')
    with audio.open('rb') as reader:
        safe_files.unlink_music(tmp_path, 'audio.mp3')
        assert reader.read() == b'fixture original'
    assert not audio.exists()


@pytest.mark.parametrize('header,body', [
    ('bytes 0-3/8', b'ab'), ('bytes 0-3/8', b'abcde'), ('bytes 4-7/8', b'abcd'),
])
def test_truncated_oversized_or_mismatched_ranges_are_not_spliced(header, body):
    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(206, headers={'Content-Range': header}, content=body))
        async with httpx.AsyncClient(transport=transport) as c:
            return b''.join([part async for part in relay_ranged(c, 'https://fixture/audio', {}, 0, 7, chunk_size=4)])
    with pytest.raises(httpx.RemoteProtocolError):
        asyncio.run(run())


def test_stream_url_cache_is_bounded_and_discards_expired_entries():
    now = [1]
    cache = StreamInfoCache(max_entries=3, ttl_s=2, clock=lambda: now[0])
    for i in range(1000):
        cache.put(str(i), 'https://fixture', {})
    assert len(cache._entries) == 3
    now[0] = 4
    cache.put('fresh', 'https://fixture', {})
    assert len(cache._entries) == 1
    assert parse_range('bytes=' + '9' * 5000 + '-') is None


def test_cache_slow_miss_does_not_block_other_user_hit(tmp_path, monkeypatch):
    monkeypatch.setenv('MUSIC_CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setattr(audio_cache, 'MUSIC_DIR', str(tmp_path / 'music'))
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def fetch(url, maximum):
            if url == 'https://slow':
                entered.set()
                await release.wait()
            return b'fixture', 'audio/mpeg'
        monkeypatch.setattr(audio_cache, 'fetch', fetch)
        await audio_cache.get('bob', 'cached', 'https://fast')
        slow = asyncio.create_task(audio_cache.get('alice', 'uncached', 'https://slow'))
        await entered.wait()
        try:
            result = await asyncio.wait_for(audio_cache.get('bob', 'cached', 'https://fast'), timeout=.5)
            assert result[0] == b'fixture'
        finally:
            release.set()
            await slow
    asyncio.run(run())


def test_cache_disk_full_preserves_playback_and_releases_fill_slot(tmp_path, monkeypatch):
    monkeypatch.setenv('MUSIC_CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setattr(audio_cache, 'MUSIC_DIR', str(tmp_path / 'music'))
    def full(*args):
        raise OSError(errno.ENOSPC, 'simulated disk full')
    async def fetch(*args):
        return b'fixture', 'audio/mpeg'
    monkeypatch.setattr(audio_cache, 'atomic', full)
    monkeypatch.setattr(audio_cache, 'fetch', fetch)
    assert asyncio.run(audio_cache.get('alice', 'one', 'https://fixture'))[0] == b'fixture'
    assert not audio_cache._inflight


def test_cancelled_cache_disk_worker_keeps_lock_until_its_write_finishes():
    entered, release, finished = Event(), Event(), Event()
    def disk_work():
        entered.set()
        assert release.wait(2)
        finished.set()
    async def run():
        guard = asyncio.Lock()
        async def write():
            async with guard:
                await safe_files.run_blocking(disk_work)
        task = asyncio.create_task(write())
        await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        assert guard.locked() and not finished.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set() and not guard.locked()
    asyncio.run(run())


def test_cancelled_file_request_retains_staging_and_reservation_until_worker_finishes(tmp_path):
    from tempfile import TemporaryDirectory
    entered, release = Event(), Event()
    files = []
    def copy(path):
        entered.set()
        assert release.wait(2)
        assert path.read_bytes() == b'staged'
    async def run():
        async def request():
            with operations.reserve('fixture-library', 'source'):
                with TemporaryDirectory(dir=tmp_path) as stage:
                    path = Path(stage) / 'audio'
                    path.write_bytes(b'staged')
                    files.append(path)
                    await safe_files.run_blocking(copy, path)
        task = asyncio.create_task(request())
        await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()  # Shutdown can cancel an already disconnected request again.
        await asyncio.sleep(0)
        with pytest.raises(HTTPException):
            with operations.reserve('fixture-library', 'source'):
                pass
        assert files[0].exists()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not files[0].exists()
        with operations.reserve('fixture-library', 'source'):
            pass
    asyncio.run(run())


def test_database_contention_is_bounded_retryable_and_preserves_playlist(private):
    original = store.write_playlist('alice-id', PlaylistWrite(name='Keep me', revision=0, items=[]))
    lock = sqlite3.connect(db.DB_PATH.parent / 'music.db')
    lock.execute('BEGIN IMMEDIATE')
    start = time.monotonic()
    try:
        with pytest.raises(HTTPException) as error:
            store.write_playlist('alice-id', PlaylistWrite(name='Changed', revision=1, items=[]), original['id'])
        assert error.value.status_code == 503 and error.value.headers == {'Retry-After': '1'}
        assert time.monotonic() - start < 1
    finally:
        lock.rollback()
        lock.close()
    assert store.playlist('alice-id', original['id']) == original
    assert store.write_playlist('alice-id', PlaylistWrite(name='Changed', revision=1, items=[]), original['id'])['revision'] == 2


def test_locked_database_reaches_real_http_stack_as_retryable_503(private):
    from fastapi.testclient import TestClient

    from main import app
    lock = sqlite3.connect(db.DB_PATH.parent / 'music.db')
    lock.execute('BEGIN IMMEDIATE')
    try:
        response = TestClient(app).post('/api/mixed-playlists', headers={'X-Session-Id': private['id']},
                                        json={'name':'Fixture', 'revision':0, 'items':[]})
    finally:
        lock.rollback()
        lock.close()
    assert response.status_code == 503 and response.headers['Retry-After'] == '1'
    assert store.playlists('alice-id') == []


def test_playlist_index_returns_summaries_without_loading_track_payloads(private):
    item = {'id': str(uuid4()), 'track': {'source': 'authorized_http', 'source_id': 'one', 'title': 'T', 'artist': 'A'}}
    saved = store.write_playlist('alice-id', PlaylistWrite(name='Full', revision=0, items=[item]))
    result = store.playlists('alice-id')
    # Summaries carry only the first artwork references, never the track payloads.
    assert result == [{k: v for k, v in saved.items() if k != 'items'} | {
        'item_count': 1, 'covers': [{'source': 'authorized_http', 'source_id': 'one', 'cover': None}]}]
    assert store.playlists('bob-id') == []
    assert store.playlist('alice-id', saved['id'])['items'] == saved['items']


def test_unacknowledged_delivery_lease_recovers_without_restart(private, monkeypatch):
    track = Track(source='authorized_http', source_id='one', artist='Fixture', title='Tone', duration=40)
    event = listening.Listen(id=uuid4(), track=track, started_at=int(time.time())-30, listened_seconds=20)
    listening.accept('alice-id', event)
    with store.connection(write=True) as c:
        c.execute("UPDATE outbox SET state='sending',next_try=0")
    monkeypatch.setattr(integrations, 'account', lambda user: {'koito_url': 'http://private-koito'})
    monkeypatch.setattr(integrations, 'koito_token', lambda user: 'fictional-token')
    sent = []
    def post(request):
        sent.append(request.content)
        return httpx.Response(200, json={'status':'ok'})
    original = httpx.AsyncClient
    monkeypatch.setattr(listening.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(post), **kw))
    asyncio.run(listening.deliver_pending())
    asyncio.run(listening.deliver_pending())
    assert len(sent) == 1
    with store.connection() as c:
        assert c.execute('SELECT state FROM outbox').fetchone()[0] == 'sent'


def test_large_failed_outbox_does_not_starve_another_user(private, monkeypatch):
    track = Track(source='authorized_http', source_id='one', artist='Fixture', title='Tone', duration=40)
    for user, count in [('alice-id', 40), ('bob-id', 1)]:
        for _ in range(count):
            listening.accept(user, listening.Listen(id=uuid4(), track=track, started_at=int(time.time())-30, listened_seconds=20))
    monkeypatch.setattr(integrations, 'account', lambda user: {'koito_url': 'http://' + user})
    monkeypatch.setattr(integrations, 'koito_token', lambda user: 'fictional-token')
    order = []
    def post(request):
        order.append(request.url.host)
        return httpx.Response(503 if request.url.host == 'alice-id' else 200, json={'status':'ok'})
    original = httpx.AsyncClient
    monkeypatch.setattr(listening.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(post), **kw))
    asyncio.run(listening.deliver_pending())
    assert order[:2] == ['alice-id', 'bob-id']
    with store.connection() as c:
        assert c.execute("SELECT state FROM outbox WHERE owner='bob-id'").fetchone()[0] == 'sent'
