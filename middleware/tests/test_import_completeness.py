import asyncio
import json

import httpx
import pytest

from services import spotify_client as sp

HTTP_CLIENT = httpx.AsyncClient


def api(monkeypatch, tmp_path, count, failure=None):
    token = tmp_path / 'token'
    token.write_text('fictional-only')
    monkeypatch.setenv('MUSIC_SPOTIFY_METADATA_TOKEN_FILE', str(token))
    original = HTTP_CLIENT
    def response(request):
        assert request.url.host == 'api.spotify.com'
        offset = int(request.url.params.get('offset', 0))
        if not request.url.path.endswith('/items'):
            return httpx.Response(200, json={'name':'Fixture','snapshot_id':'stable','items':{'total':count}})
        if offset == 50 and failure == 'error':
            return httpx.Response(503)
        entries = [{'item': {'name':f'Song {i % 49}', 'uri':f'spotify:track:{i % 49}',
                             'type':'track','artists':[{'name':'Fixture'}],'duration_ms':200000}}
                   for i in range(offset, min(count, offset+50))]
        return httpx.Response(200, json={'items':entries, 'total':count,
                                        'offset':0 if failure == 'repeat' else offset})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(response), **kw))


@pytest.mark.parametrize('count', [99,100,101,300])
def test_all_positions_and_intentional_repeats(monkeypatch, tmp_path, count):
    api(monkeypatch, tmp_path, count)
    result = asyncio.run(sp.fetch_playlist('spotify:playlist:fixture'))
    assert result['source_complete'] and len(result['tracks']) == count
    assert [t['source_position'] for t in result['tracks']] == list(range(count))
    assert result['tracks'][0]['source_id'] == result['tracks'][49]['source_id']


@pytest.mark.parametrize('failure,reason', [('repeat','page_inconsistent'),('error','page_failed')])
def test_repeated_page_and_intermediate_failure(monkeypatch, tmp_path, failure, reason):
    api(monkeypatch, tmp_path, 300, failure)
    partial = asyncio.run(sp.fetch_playlist('spotify:playlist:fixture'))
    assert partial['retrieved'] == 50 and partial['source_total'] == 300
    assert partial['source_warning'] == reason and not partial['source_complete']
    api(monkeypatch, tmp_path, 300)
    full = asyncio.run(sp.fetch_playlist('spotify:playlist:fixture'))
    assert full['tracks'][:50] == partial['tracks']


def test_embed_does_not_claim_completeness_or_discard_unavailable(monkeypatch):
    monkeypatch.delenv('MUSIC_SPOTIFY_METADATA_TOKEN_FILE', raising=False)
    original = HTTP_CLIENT
    data = {'props':{'pageProps':{'state':{'data':{'entity':{'name':'Fixture','trackList':[
        {'title':'One','subtitle':'Fixture'}, {}, {'title':'One','subtitle':'Fixture'}]}}}}}}
    html = '<script id="__NEXT_DATA__">'+json.dumps(data)+'</script>'
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(
        transport=httpx.MockTransport(lambda r: httpx.Response(200,text=html)), **kw))
    result = asyncio.run(sp.fetch_playlist('spotify:playlist:fixture'))
    assert len(result['tracks']) == 3 and result['tracks'][1]['source_unavailable']
    assert result['source_total'] is None and not result['source_complete']


def test_total_time_budget_preserves_verified_prefix(monkeypatch, tmp_path):
    token = tmp_path/'token'
    token.write_text('fictional')
    monkeypatch.setenv('MUSIC_SPOTIFY_METADATA_TOKEN_FILE', str(token))
    original_timeout = asyncio.timeout
    monkeypatch.setattr(sp.asyncio, 'timeout', lambda _: original_timeout(.02))
    async def response(request):
        if not request.url.path.endswith('/items'):
            return httpx.Response(200,json={'name':'Fixture','snapshot_id':'s','items':{'total':101}})
        offset = int(request.url.params['offset'])
        if offset:
            await asyncio.sleep(.1)
        return httpx.Response(200,json={'offset':offset,'total':101,'items':[
            {'item':{'name':str(i),'artists':[{'name':'Fixture'}],'duration_ms':200000}} for i in range(50)]})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:HTTP_CLIENT(transport=httpx.MockTransport(response),**kw))
    result = asyncio.run(sp.fetch_playlist('spotify:playlist:fixture'))
    assert result['retrieved'] == 50 and result['source_warning'] == 'time_budget'
    assert not result['source_complete']


def exported(count, repeat_every=49):
    rows = ['"Track URI","Track Name","Album Name","Artist Name(s)","Duration (ms)","ISRC"']
    rows += [f'"spotify:track:{i % repeat_every}","Song, {i % repeat_every}","Album","Fixture;Guest","200000","ES{i % repeat_every:010d}"'
             for i in range(count)]
    return '﻿' + '\r\n'.join(rows) + '\r\n'


@pytest.mark.parametrize('count', [99, 100, 101, 300])
def test_owner_export_recovers_every_position_with_repeats(count):
    result = sp.parse_export(exported(count), ' Mi lista ')
    assert result['name'] == 'Mi lista' and result['metadata_source'] == 'file'
    assert result['source_complete'] and result['source_total'] == result['retrieved'] == count
    assert [t['source_position'] for t in result['tracks']] == list(range(count))
    first = result['tracks'][0]
    assert first == {'title': 'Song, 0', 'artist': 'Fixture, Guest', 'artists': ['Fixture', 'Guest'], 'album_artist': None,
                     'album': 'Album', 'duration': 200.0, 'source_position': 0,
                     'source_id': 'spotify:track:0', 'isrc': 'ES0000000000', 'details': {}, 'source_unavailable': False}
    assert result['tracks'][49]['source_id'] == first['source_id']  # An intentional repeat is kept.


def test_owner_export_reports_its_own_limit_and_keeps_rows_without_title():
    liked = sp.parse_export(exported(1830), 'Me gusta')
    assert liked['retrieved'] == liked['source_total'] == 1830 and liked['source_complete']
    big = sp.parse_export(exported(sp.FILE_LIMIT + 1), 'Grande')
    assert big['retrieved'] == sp.FILE_LIMIT and big['source_total'] == sp.FILE_LIMIT + 1
    assert not big['source_complete'] and big['source_warning'] == 'resource_limit'
    odd = sp.parse_export('Track Name,Artist Name(s)\nUno,Ana\n,Ana\nDos,"Ana, Luis"\n', 'x')
    assert [t['source_unavailable'] for t in odd['tracks']] == [False, True, False]
    assert odd['tracks'][2]['artist'] == 'Ana, Luis' and odd['tracks'][2]['duration'] is None


def test_plain_text_export_and_rejections():
    plain = sp.parse_export('Ana - Uno\n\nAna - Dos - En directo\n', 'Texto')
    assert [(t['artist'], t['title']) for t in plain['tracks']] == [('Ana', 'Uno'), ('Ana', 'Dos - En directo')]
    for bad in ('', '   \n', 'Ana - Uno\nsin separador\n'):
        with pytest.raises(sp.SpotifyError):
            sp.parse_export(bad, 'x')


def test_client_credentials_token_is_requested_once_and_never_returned(monkeypatch, tmp_path):
    monkeypatch.delenv('MUSIC_SPOTIFY_METADATA_TOKEN_FILE', raising=False)
    client = tmp_path / 'client.json'
    client.write_text(json.dumps({'client_id': 'fictional-id', 'client_secret': 'fictional-secret'}))
    monkeypatch.setenv('MUSIC_SPOTIFY_CLIENT_FILE', str(client))
    monkeypatch.setattr(sp, '_client_token', {'value': None, 'expires': 0.0, 'file': None})
    issued = []
    def response(request):
        if request.url.host == 'accounts.spotify.com':
            assert request.headers['authorization'].startswith('Basic ') and b'client_credentials' in request.content
            issued.append(1)
            return httpx.Response(200, json={'access_token': 'short-lived', 'expires_in': 3600})
        assert request.headers['authorization'] == 'Bearer short-lived'
        offset = int(request.url.params.get('offset', 0))
        if not request.url.path.endswith('/items'):
            return httpx.Response(200, json={'name': 'Fixture', 'snapshot_id': 's', 'items': {'total': 101}})
        return httpx.Response(200, json={'offset': offset, 'total': 101, 'items': [
            {'item': {'name': str(i), 'artists': [{'name': 'Fixture'}], 'duration_ms': 200000}} for i in range(offset, min(101, offset + 50))]})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: HTTP_CLIENT(transport=httpx.MockTransport(response), **kw))
    for _ in range(2):
        result = asyncio.run(sp.fetch_playlist('spotify:playlist:fixture'))
        assert result['source_complete'] and result['retrieved'] == 101
        assert 'short-lived' not in json.dumps(result) and 'fictional-secret' not in json.dumps(result)
    assert len(issued) == 1


def test_exportify_csv_is_read_as_exported():
    """Header and quoting as written by Exportify (github.com/watsonbox/exportify)."""
    header = ('"Track URI","Track Name","Artist URI(s)","Artist Name(s)","Album URI","Album Name","Album Artist URI(s)",'
              '"Album Artist Name(s)","Album Release Date","Album Image URL","Disc Number","Track Number",'
              '"Track Duration (ms)","Track Preview URL","Explicit?","Popularity","ISRC","Added By","Added At"')
    rows = [
        '"spotify:track:1","Lil GZ 1995","spotify:artist:a, spotify:artist:b","Hard GZ, LIL GZ","spotify:album:x","Lil GZ 1995",'
        '"spotify:artist:a","Hard GZ","2019-01-01","https://img","1","1","151723","","true","40","ES5701900001","spotify:user:u","2020-01-01T00:00:00Z"',
        '"spotify:track:2","Say ""Hi""","spotify:artist:c","Tyler\\, The Creator","spotify:album:y","Disco","spotify:artist:c",'
        '"Tyler\\, The Creator","2020","https://img","1","2","200000","","false","50","USABC2000002","spotify:user:u","2020-01-02T00:00:00Z"',
    ]
    playlist = sp.parse_export("﻿" + "\n".join([header, *rows]), "Mi lista")
    first, second = playlist["tracks"]
    assert (first["title"], first["artist"], first["album"], first["isrc"]) == ("Lil GZ 1995", "Hard GZ, LIL GZ", "Lil GZ 1995", "ES5701900001")
    assert abs(first["duration"] - 151.723) < 1e-6 and first["source_id"] == "spotify:track:1"
    assert second["title"] == 'Say "Hi"' and second["artist"] == "Tyler, The Creator"
    assert playlist["source_complete"] and playlist["source_total"] == 2


def test_spanish_exportify_300_rows_preserves_metadata_order_and_duplicates():
    # Localized header observed in the user's export; all row data is fictional.
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['URI de la canción', 'Nombre de la canción', 'URI(s) del artista',
                     'Nombre(s) del artista', 'URI del álbum', 'Nombre del álbum',
                     'Duración de la canción (ms)', 'ISRC'])
    for n in range(300):
        number = n if n != 299 else 0  # Intentional duplicate, not an accidental repeated page.
        writer.writerow([f'spotify:track:fixture{number}', f'Canción {number}', 'spotify:artist:fixture',
                         'Artista uno, Artista dos', 'spotify:album:fixture', 'Álbum sintético',
                         '229123', 'ESABC2600001'])
    result = sp.parse_export('\ufeff' + output.getvalue(), 'Solo laboratorio')
    assert result['source_complete'] and result['retrieved'] == result['source_total'] == 300
    assert [r['title'] for r in result['tracks']] == [f'Canción {n}' for n in range(299)] + ['Canción 0']
    row = result['tracks'][0]
    assert row['artist'] == 'Artista uno, Artista dos'
    assert row['album'] == 'Álbum sintético' and row['duration'] == 229.123
    assert row['isrc'] == 'ESABC2600001' and row['source_id'] == 'spotify:track:fixture0'
    assert result['tracks'][-1]['source_position'] == 299
