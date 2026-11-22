"""Bounded search expansion; matching thresholds are unchanged."""
from anyio import to_thread
from pydantic import ValidationError

from homelab import matcher
from homelab.models import Track
from services import ytdlp_service


def queries(track):
    artist, title = track['artist'], track['title']
    options = [f'{artist} {title}']
    if track.get('isrc'):
        options.append(track['isrc'])
    if track.get('album'):
        options.append(f'{title} {artist} {track["album"]}')
    if ',' in artist:
        options.append(f'{artist.split(",")[0]} {title}')
    options.append(f'"{title}" {artist}')
    return list(dict.fromkeys(options))[:3]


async def resolve(track, active, query=None):
    candidates, attempts, errors = [], [], 0
    ranked = matcher.rank(track, [])
    for text in [query] if query else queries(track):
        active()
        try:
            raw = await to_thread.run_sync(lambda text=text: ytdlp_service.search(text, limit=5, source='youtube_music'))
            active()
        except (RuntimeError, ValueError, OSError):
            errors += 1
            attempts.append({'result': 'provider_error'})
            continue
        attempts.append({'result': 'ok', 'count': len(raw)})
        for r in raw:
            try:
                candidates.append(Track(source='youtube', source_id=r['videoId'], title=r['title'],
                                        artist=r.get('channel') or 'Unknown', album=r.get('album') or '',
                                        duration=r.get('duration') or None, isrc=r.get('isrc'),
                                        recording_mbid=r.get('recording_mbid')))
            except (ValidationError, KeyError):
                errors += 1
        ranked = matcher.rank(track, candidates)
        if ranked['selected']:
            break
    ranked['attempts'] = attempts
    ranked['provider_errors'] = errors
    return ranked
