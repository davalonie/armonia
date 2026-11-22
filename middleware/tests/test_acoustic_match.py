import asyncio
import json

from homelab import acoustic_match as a


def test_no_reference_never_claims_comparison(monkeypatch):
    monkeypatch.delenv('MUSIC_ACOUSTIC_MANIFEST', raising=False)
    result = asyncio.run(a.resolve({}, [], 'alice', lambda:None))
    assert result['status'] == 'no_reference' and result['compared'] == 0


def test_private_reference_full_audio_and_conflict_abstention(monkeypatch, tmp_path):
    manifest = tmp_path/'manifest.json'
    ref = {'owner':'alice','authorized':True,'identity_verified':True,'isrc':'ESAAA2600001','scope':'complete_recording','path':'ref.wav',
           'candidates':[{'source':'youtube','source_id':'abcdefghijk','path':'candidate.wav','authorized':True}]}
    manifest.write_text(json.dumps({'references':[ref]}))
    monkeypatch.setenv('MUSIC_ACOUSTIC_MANIFEST',str(manifest))
    async def pcm(path,root): return {'hash':'whole-recording-hash','bytes':10000000,'seconds':200,'fingerprint':[]}
    monkeypatch.setattr(a,'_pcm',pcm)
    wanted = {'title':'Song','artist':'Fixture','duration':200,'isrc':'ESAAA2600001'}
    candidate = {'track':{'title':'Song','artist':'Other credits','duration':200,'source':'youtube','source_id':'abcdefghijk'}}
    assert asyncio.run(a.resolve(wanted,[candidate],'bob',lambda:None))['status'] == 'no_reference'
    result = asyncio.run(a.resolve(wanted,[candidate],'alice',lambda:None))
    assert result['selected'] and result['compared'] == 1
    reference_scope = ref.pop('scope')
    manifest.write_text(json.dumps({'references':[ref]}))
    assert asyncio.run(a.resolve(wanted,[candidate],'alice',lambda:None))['selected'] is None
    ref['scope'] = reference_scope
    manifest.write_text(json.dumps({'references':[ref]}))
    second = {'track':{**candidate['track'], 'source_id':'abcdefghijl'}}
    ref['candidates'].append({'source':'youtube','source_id':'abcdefghijl','path':'same.wav','authorized':True})
    manifest.write_text(json.dumps({'references':[ref]}))
    assert asyncio.run(a.resolve(wanted,[candidate,second],'alice',lambda:None))['status'] == 'ambiguous'
    candidate['track']['title'] = 'Song Live'
    assert asyncio.run(a.resolve(wanted,[candidate],'alice',lambda:None))['selected'] is None
    candidate['track']['title'] = 'Song'
    async def changed(path,root): return {'hash':path,'bytes':10000000,'seconds':200,'fingerprint':[]}
    monkeypatch.setattr(a,'_pcm',changed)
    assert asyncio.run(a.resolve(wanted,[candidate],'alice',lambda:None))['status'] == 'not_exact_uncalibrated'


def test_alignment_and_shared_excerpt_never_confirm_full_recording():
    import random
    rng = random.Random(12)
    reference = [rng.getrandbits(32) for _ in range(500)]
    shifted = [rng.getrandbits(32) for _ in range(20)] + reference
    exact = a.alignment(reference, shifted)
    assert exact['bit_distance'] == 0 and exact['offset_frames'] == -20
    altered = reference[:330]+[rng.getrandbits(32) for _ in range(170)]
    result = a.alignment(reference,altered)
    assert result['regions'][2] > .3 and not result['calibrated']
    assert a.alignment(reference[:59],reference) is None


def test_real_decoder_lossless_whole_track_and_budget(tmp_path):
    """Actual FFmpeg and fingerprints, generated signal; not musical calibration."""
    import math
    import shutil
    import struct
    import subprocess
    import wave

    import pytest
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg unavailable')
    path = tmp_path/'reference.wav'
    rate = 11025
    with wave.open(str(path),'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b''.join(struct.pack('<h',int(5000*math.sin(2*math.pi*(220+55*(i//rate%5))*i/rate))) for i in range(32*rate)))
    flac = tmp_path/'same.flac'
    subprocess.run(['ffmpeg','-v','error','-i',str(path),str(flac)],check=True,timeout=10)
    async def run():
        first=await a._pcm('reference.wav',tmp_path)
        second=await a._pcm('same.flac',tmp_path)
        assert first['hash']==second['hash'] and first['seconds']==32
        assert a.alignment(first['fingerprint'],second['fingerprint'])['bit_distance']==0
        with pytest.raises(ValueError):
            await a._pcm('../outside.wav',tmp_path)
    asyncio.run(run())
