"""Durable publication intent: simulated interruption never needs Navidrome scan."""
import asyncio
import errno
import subprocess
import sys
from pathlib import Path
from threading import Event

import pytest
from fastapi import BackgroundTasks, HTTPException
from mutagen.id3 import ID3

import db
import jobs
from homelab import publications, store
from homelab.models import PlaylistWrite
from routes import download
from routes import sources as source_routes
from services import safe_files
from services import ytdlp_service as yt


class Interrupted(BaseException):
    """Injected process stop; ordinary application error handlers do not catch it."""


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'armonia.db')
    db.init_db()
    store.init()
    root = tmp_path / 'music'
    root.mkdir()
    monkeypatch.setattr(safe_files, 'MUSIC_DIR', str(root))
    monkeypatch.setattr(yt, 'MUSIC_DIR', str(root))
    monkeypatch.setenv('MUSIC_FREE_SPACE_RESERVE_BYTES', '0')
    sid = db.create_session('alice', 's', 't', str(root), library_id=7, user_id='alice-id')
    jobs._jobs.clear()
    jobs._active_video_ids.clear()
    jobs._cancelled.clear()
    async def grant(sess):
        db.require_active_session(sess)
        return 7
    async def missing(*args):
        return False
    async def none(*args):
        return set()
    monkeypatch.setattr(download.navidrome_client, 'require_library_access', grant)
    monkeypatch.setattr(download.navidrome_client, 'matching_song_ids', none)
    monkeypatch.setattr(download, '_is_duplicate', missing)
    metadata = {'artist':'Fixture', 'title':'Tone'}
    monkeypatch.setattr(download.sources, 'allowed', lambda *a: {'metadata': metadata})
    monkeypatch.setattr(yt.tagger_service, 'tag', lambda *args: None)
    def stage(video, artist, title, source, cancel, directory):
        result = Path(directory) / 'fixture.mp3'
        result.write_bytes(b'fictional audio')
        return str(result), {}
    monkeypatch.setattr(yt, '_download_staged', stage)
    return root, db.get_session(sid)


def test_failed_intent_commit_never_publishes_audio(lab, tmp_path):
    root, _ = lab
    stage = tmp_path / 'audio.mp3'
    stage.write_bytes(b'fixture')
    def full(path):
        raise OSError(errno.ENOSPC, 'simulated database disk full')
    with pytest.raises(OSError):
        safe_files.publish(stage, root, 'Fixture', 'Tone', record_intent=full)
    assert not [p for p in root.rglob('*') if p.is_file()]


def test_receipt_without_file_allows_retry_and_is_scoped_to_library(lab):
    root, _ = lab
    target = root / 'not-published.mp3'
    publications.record(root, 'authorized_http:one', str(target))
    publications.require_unpublished(root, 'authorized_http:one')
    target.write_bytes(b'fixture')
    with pytest.raises(HTTPException) as error:
        publications.require_unpublished(root, 'authorized_http:one')
    assert error.value.status_code == 409
    publications.require_unpublished(root / 'bob', 'authorized_http:one')
    publications.require_unpublished(root, 'authorized_http:another')


def test_receipt_never_follows_links_or_accepts_foreign_paths(lab, tmp_path):
    root, _ = lab
    outside = tmp_path / 'private'
    outside.write_bytes(b'do not read')
    with pytest.raises(ValueError):
        publications.record(root, 'authorized_http:one', str(outside))
    target = root / 'link.mp3'
    target.symlink_to(outside)
    publications.record(root, 'authorized_http:one', str(target))
    with pytest.raises(HTTPException) as error:
        publications.require_unpublished(root, 'authorized_http:one')
    assert error.value.status_code == 409 and outside.read_bytes() == b'do not read'


def test_schema_three_upgrade_preserves_data_and_is_repeatable(lab):
    playlist = store.write_playlist('alice-id', PlaylistWrite(name='Keep me', revision=0, items=[]))
    with store.connection(write=True) as c:
        c.execute('DROP TABLE publication_intents')  # Construct a private v3 fixture.
        c.execute('PRAGMA user_version=3')
    store.init()
    store.init()
    assert store.playlist('alice-id', playlist['id']) == playlist
    with store.connection() as c:
        assert c.execute('PRAGMA user_version').fetchone()[0] == 4
        assert c.execute('SELECT count(*) FROM publication_intents').fetchone()[0] == 0


def test_job_crash_after_rename_preserves_intent_and_blocks_all_unforced_retries(lab, monkeypatch):
    root, sess = lab
    job = jobs.create_job('abcdefghijk', 'Fixture', 'Tone', 'nd:alice-id')
    rename = safe_files.os.rename
    def stop_after_commit(*args, **kw):
        rename(*args, **kw)
        raise Interrupted()
    monkeypatch.setattr(safe_files.os, 'rename', stop_after_commit)
    with pytest.raises(Interrupted):
        asyncio.run(download._run_download(job.job_id, job.video_id, job.artist, job.title,
                    sess['username'], sess['salt'], sess['token'], str(root), session=sess))
    record = db.get_download_record(job.job_id)
    assert Path(record['file_path']).read_bytes() == b'fictional audio'
    db.init_db()  # Process restart: persisted state survives, memory does not.
    jobs._jobs.clear()
    jobs._active_video_ids.clear()
    store.init()
    monkeypatch.setattr(safe_files.os, 'rename', rename)
    with pytest.raises(HTTPException) as error:
        asyncio.run(download.retry_download(job.job_id, BackgroundTasks(), sess))
    assert error.value.status_code == 409
    async def grant():
        return 7
    with pytest.raises(HTTPException) as error:
        asyncio.run(yt.download_limited(job.video_id, 'Fixture', 'Tone', music_dir=str(root), authorize=grant))
    assert error.value.status_code == 409
    assert len(list(root.rglob('*.mp3'))) == 1
    # Explicit force remains an intentional, separately requested second copy.
    asyncio.run(yt.download_limited(job.video_id, 'Fixture', 'Tone', music_dir=str(root), authorize=grant, allow_repeat=True))
    assert len(list(root.rglob('*.mp3'))) == 2


def test_job_intent_without_rename_can_be_retried(lab, monkeypatch):
    root, sess = lab
    job = jobs.create_job('abcdefghijk', 'Fixture', 'Tone', 'nd:alice-id')
    rename = safe_files.os.rename
    def stop_before_commit(*args, **kw):
        raise Interrupted()
    monkeypatch.setattr(safe_files.os, 'rename', stop_before_commit)
    with pytest.raises(Interrupted):
        asyncio.run(download._run_download(job.job_id, job.video_id, job.artist, job.title,
                    sess['username'], sess['salt'], sess['token'], str(root), session=sess))
    record = db.get_download_record(job.job_id)
    assert record['file_path'] and not Path(record['file_path']).exists()
    db.init_db()
    jobs._jobs.clear()
    jobs._active_video_ids.clear()
    monkeypatch.setattr(safe_files.os, 'rename', rename)
    tasks = BackgroundTasks()
    assert asyncio.run(download.retry_download(job.job_id, tasks, sess))['status'] == 'pending'
    assert len(tasks.tasks) == 1


def test_failed_forced_copy_does_not_replace_receipt_for_existing_recording(lab, monkeypatch):
    root, _ = lab
    async def grant():
        return 7
    original = asyncio.run(yt.download_limited('abcdefghijk', 'Fixture', 'Tone', music_dir=str(root), authorize=grant))
    rename = safe_files.os.rename
    def stop_before_commit(*args, **kw):
        raise Interrupted()
    monkeypatch.setattr(safe_files.os, 'rename', stop_before_commit)
    with pytest.raises(Interrupted):
        asyncio.run(yt.download_limited('abcdefghijk', 'Fixture', 'Tone', music_dir=str(root), authorize=grant, allow_repeat=True))
    monkeypatch.setattr(safe_files.os, 'rename', rename)
    with pytest.raises(HTTPException) as error:
        asyncio.run(yt.download_limited('abcdefghijk', 'Fixture', 'Tone', music_dir=str(root), authorize=grant))
    assert error.value.status_code == 409
    assert list(root.rglob('*.mp3')) == [Path(original)]
    with store.connection() as c:
        assert c.execute('SELECT count(*) FROM publication_intents').fetchone()[0] == 2


@pytest.mark.parametrize('kind', ['job', 'http'])
def test_hard_process_exit_after_rename_keeps_durable_receipt(lab, tmp_path, kind):
    root, sess = lab
    stage = tmp_path / 'staged.mp3'
    stage.write_bytes(b'fixture survived process exit')
    script = '''
import os, sys
from pathlib import Path
import db
from homelab import publications
from services import safe_files
db.DB_PATH = Path(sys.argv[1])
root, stage = Path(sys.argv[2]), Path(sys.argv[3])
kind = sys.argv[4]
rename = os.rename
def stop(*args, **kwargs):
    rename(*args, **kwargs)
    os._exit(37)
os.rename = stop
def record(path):
    if kind == 'job':
        db.upsert_download('crashed-job', 'abcdefghijk', 'Fixture', 'Tone', 'downloading', username='nd:alice-id', file_path=path)
    else:
        publications.record(root, 'authorized_http:one', path)
safe_files.publish(stage, root, 'Fixture', 'Tone', record_intent=record)
'''
    process = subprocess.run([sys.executable, '-c', script, str(db.DB_PATH), str(root), str(stage), kind],
                             cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=10)
    assert process.returncode == 37, process.stderr.decode()
    db.init_db()
    store.init()
    with pytest.raises(HTTPException) as error:
        if kind == 'job':
            asyncio.run(download.retry_download('crashed-job', BackgroundTasks(), sess))
        else:
            asyncio.run(source_routes.save('one', sess))
    assert error.value.status_code == 409
    files = list(root.rglob('*.mp3'))
    assert len(files) == 1 and files[0].read_bytes() == stage.read_bytes()


@pytest.mark.parametrize('failure', ['crash', 'cancel'])
def test_http_publication_interrupted_before_scan_cannot_be_downloaded_again(lab, monkeypatch, failure):
    root, sess = lab
    renamed, release = Event(), Event()
    fetched, scans = [], []
    rename = safe_files.os.rename
    def stop_after_commit(*args, **kw):
        rename(*args, **kw)
        if failure == 'crash':
            raise Interrupted()
        renamed.set()
        assert release.wait(2)
    async def fetch(*args):
        fetched.append(True)
        return b'fictional audio', 'audio/mpeg'
    class Process:
        async def wait(self):
            return 0
    async def convert(*args, **kwargs):
        ID3().save(args[-1])
        return Process()
    async def scan(*args, **kwargs):
        scans.append(True)
        return False
    monkeypatch.setattr(source_routes.audio_cache, 'fetch', fetch)
    monkeypatch.setattr(source_routes.sources, 'audio_url', lambda *a: 'https://invalid.test/fixture')
    monkeypatch.setattr(source_routes.asyncio, 'create_subprocess_exec', convert)
    monkeypatch.setattr(source_routes.navidrome_client, 'scan_until', scan)
    monkeypatch.setattr(safe_files.os, 'rename', stop_after_commit)
    async def run():
        if failure == 'crash':
            with pytest.raises(Interrupted):
                await source_routes.save('one', sess)
        else:
            task = asyncio.create_task(source_routes.save('one', sess))
            assert await asyncio.to_thread(renamed.wait, 1)
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        store.init()  # Reopen persisted journal without relying on process memory.
        with pytest.raises(HTTPException) as error:
            await source_routes.save('one', sess)
        assert error.value.status_code == 409
    asyncio.run(run())
    assert fetched == [True] and not scans and len(list(root.rglob('*.mp3'))) == 1
