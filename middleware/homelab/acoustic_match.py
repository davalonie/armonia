"""Private, opt-in comparison of complete authorized local recordings.

Only exact decoded PCM equality may confirm automatically. Lossy similarity
requires musical calibration which is NOT available; it must abstain. No
network, Spotify previews, candidate-to-candidate references or personal audio
uploads. A trusted operator supplies the per-owner manifest and internal files.
"""
import array
import asyncio
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from homelab import matcher

MAX_BYTES = 64 * 1024**2
MAX_SECONDS = 300
_slots = asyncio.Semaphore(2)


async def _pcm(path, root):
    path = (root / path).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('file_outside_budget')
    # -fs bounds decoded output; reject the boundary rather than compare prefixes.
    with tempfile.TemporaryDirectory(prefix='armonia-acoustic-') as tmp:
        output = Path(tmp) / 'audio.pcm'
        process = await asyncio.create_subprocess_exec(
            'ffmpeg', '-v', 'error', '-nostdin', '-protocol_whitelist', 'file',
            '-format_whitelist', 'wav,flac,mp3,ogg,mov,matroska', '-i', str(path), '-map', '0:a:0', '-vn', '-t', str(MAX_SECONDS + 1),
            '-ar', '44100', '-ac', '2', '-f', 's16le', '-fs', str(MAX_BYTES), str(output),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            await process.wait()
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        size = output.stat().st_size if output.exists() else 0
        if process.returncode or size < 44100 * 4 * 30 or size >= MAX_BYTES or size > MAX_SECONDS * 44100 * 4:
            raise ValueError('audio_outside_budget')
        data = output.read_bytes()
        if len(set(data)) < 8:
            raise ValueError('insufficient_signal')
        fingerprint = Path(tmp) / 'fingerprint.raw'
        process = await asyncio.create_subprocess_exec(
            'ffmpeg', '-v', 'error', '-nostdin', '-protocol_whitelist', 'file',
            '-f', 's16le', '-ar', '44100', '-ac', '2', '-i', str(output),
            '-f', 'chromaprint', '-fp_format', 'raw', str(fingerprint),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            await process.wait()
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        frames = array.array('I')
        if process.returncode == 0 and fingerprint.stat().st_size < 16384:
            frames.frombytes(fingerprint.read_bytes())
        return {'hash':hashlib.sha256(data).hexdigest(), 'bytes':size,
                'seconds':size/(44100*4), 'fingerprint':list(frames)}


def alignment(left, right):
    """Diagnostic only: bounded alignment and three regions, NEVER a confidence score."""
    if min(len(left),len(right)) < 200:
        return None
    def distance(offset):
        a,b = max(0,offset), max(0,-offset)
        n = min(len(left)-a,len(right)-b)
        if n < 200:
            return 1.0, offset, []
        regions = []
        for j in range(3):
            start,end = n*j//3,n*(j+1)//3
            regions.append(sum((left[a+i]^right[b+i]).bit_count() for i in range(start,end))/(32*(end-start)))
        return sum(regions)/3,offset,regions
    distance_value,offset,regions = min((distance(i) for i in range(-160,161)),key=lambda r:r[0])
    return {'bit_distance':round(distance_value,5), 'offset_frames':offset,
            'regions':[round(x,5) for x in regions], 'calibrated':False}



async def resolve(wanted, candidates, owner, active):
    started = time.perf_counter()
    evidence = {'status': 'no_reference', 'method': 'complete-pcm-v1', 'compared': 0,
                'selected': None, 'network_bytes': 0}
    config = os.environ.get('MUSIC_ACOUSTIC_MANIFEST')
    if not config:
        return evidence
    try:
        async with asyncio.timeout(30), _slots:
            active()
            manifest_path = Path(config).resolve()
            if manifest_path.stat().st_size > 1024**2:
                raise ValueError('manifest_too_large')
            manifest = json.loads(manifest_path.read_text())
            root = manifest_path.parent
            entries = [r for r in manifest.get('references', []) if r.get('owner') == owner
                       and r.get('authorized') is True and r.get('identity_verified') is True
                       and any(wanted.get(k) and wanted[k] == r.get(k) for k in ('isrc', 'recording_mbid'))]
            if len(entries) != 1:
                return evidence
            ref = entries[0]
            # Conflicting identities/versions cannot be overridden by a shared passage.
            if any(wanted.get(k) and ref.get(k) and wanted[k] != ref[k] for k in ('isrc', 'recording_mbid')):
                evidence['status'] = 'identity_conflict'
                return evidence
            reference = await _pcm(ref['path'], root)
            active()
            matches = []
            evidence['alignments'] = []
            evidence['status'] = 'candidate_audio_unavailable'
            for candidate in candidates[:3]:
                track = candidate['track']
                audio = next((a for a in ref.get('candidates', []) if a.get('source') == track['source']
                              and a.get('source_id') == track['source_id'] and a.get('authorized') is True), None)
                if not audio:
                    continue
                active()
                decoded = await _pcm(audio['path'], root)
                active()
                evidence['compared'] += 1
                evidence['status'] = 'not_exact_uncalibrated'
                evidence['alignments'].append({'source_id':track['source_id'],
                                               'analysis':alignment(reference['fingerprint'],decoded['fingerprint'])})
                conflicts = matcher.score(wanted, track)['reasons']
                expected = wanted.get('duration') or ref.get('duration')
                complete = ref.get('scope') == 'complete_recording' and type(expected) in (int,float) and expected > 0 and abs(reference['seconds']-expected) <= max(3,expected*.02)
                if complete and decoded['hash'] == reference['hash'] and decoded['bytes'] == reference['bytes'] and not any('version' in r or 'conflicting' in r or 'duration differs' == r
                                                     for r in conflicts):
                    matches.append(track)
            if len(matches) == 1:
                evidence.update(status='confirmed_exact_audio', selected=matches[0])
            elif matches:
                evidence['status'] = 'ambiguous'
    except TimeoutError:
        evidence['status'] = 'budget_exhausted'
    except (OSError, ValueError, KeyError, TypeError):
        evidence['status'] = 'reference_unavailable'
    finally:
        evidence['seconds'] = round(time.perf_counter() - started, 6)
    return evidence
