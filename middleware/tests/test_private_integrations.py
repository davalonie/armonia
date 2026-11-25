import asyncio
import json
import time
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import db
import internal_main
from auth import get_current_session
from homelab import artist_ids, discovery_profile, integrations, listening, store
from homelab.models import Track
from routes import discover
from routes import listening as listening_routes


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(discover, '_last_refresh', {})
    monkeypatch.setattr(db, 'require_active_session', lambda sess: None)
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'armonia.db')
    monkeypatch.delenv('MUSIC_SECRET_KEY_FILE', raising=False)
    store.init()
    users = {}
    for name, remote in [('alice', 1), ('bob', 2)]:
        token = tmp_path / (name + '.token')
        token.write_text(name + '-private-koito-token')
        users[name] = {'aurral_user_id': remote, 'koito_url': 'http://koito-' + name,
                       'koito_token_file': str(token), 'bridge_key': name[0] * 43}
    config = tmp_path / 'integrations.json'
    config.write_text(json.dumps({'users': users, 'aurral_url': 'http://aurral', 'bridge_origin': 'http://music:8001'}))
    monkeypatch.setenv('MUSIC_INTEGRATIONS_FILE', str(config))
    app = FastAPI()
    app.include_router(discover.router)
    app.include_router(listening_routes.router)
    client = TestClient(app)
    def as_user(name):
        app.dependency_overrides[get_current_session] = lambda: {'user_id': name}
    client.as_user = as_user
    client.as_user('alice')
    return client, config


@pytest.fixture
def transport(monkeypatch):
    original = httpx.AsyncClient
    def install(handler):
        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    return install


def event(**changes):
    value = {'id': str(uuid4()), 'started_at': int(time.time()) - 120, 'listened_seconds': 100,
             'track': {'source': 'authorized_http', 'source_id': 'fixture', 'title': 'Song', 'artist': 'Fixture', 'duration': 200}}
    value.update(changes)
    return value


def test_local_recording_gets_artist_mbid_from_get_artist_not_song_ref(lab, transport):
    client, _ = lab
    app = client.app
    app.dependency_overrides[get_current_session] = lambda: {'user_id': 'alice', 'username': 'alice', 'salt': 'fictional', 'token': 'private-nd-token'}
    calls = []
    def upstream(request):
        calls.append(request.url.path)
        assert request.url.params['u'] == 'alice' and request.url.params['t'] == 'private-nd-token'
        if request.url.path.endswith('getSong'):
            body = {'song': {'id': 'song', 'title': 'Song', 'artist': 'Artist', 'duration': 200, 'artists': [{'id': 'artist-id', 'name': 'Artist'}]}}
        else:
            assert request.url.path.endswith('getArtist') and request.url.params['id'] == 'artist-id'
            body = {'artist': {'name': 'Artist', 'musicBrainzId': '11111111-1111-4111-8111-111111111111'}}
        return httpx.Response(200, json={'subsonic-response': {'status': 'ok', **body}})
    transport(upstream)
    value = event()
    value['track'].update(source='navidrome', source_id='song')
    assert client.post('/api/listening/events', json=value).status_code == 202
    assert client.post('/api/listening/events', json=value).json()['duplicate']
    assert len(calls) == 2  # A changed/unavailable upstream cannot change an accepted replay.
    with store.connection() as c:
        row = c.execute('SELECT payload,canonical FROM play_events WHERE owner=?', ('alice',)).fetchone()
        assert not json.loads(row[0])['track']['artist_mbids']
        assert json.loads(row[1])['track']['artist_mbids'] == ['11111111-1111-4111-8111-111111111111']


def test_replay_keeps_original_resolution_even_after_tags_change(lab):
    value = listening.Listen(**event())
    canonical = Track(**{**value.track.model_dump(), 'artist': 'Canonical Artist'})
    listening.accept('alice', value, canonical)
    assert listening.accept('alice', value, canonical.model_copy(update={'artist': 'Changed'}))['duplicate']
    with store.connection() as c:
        assert json.loads(c.execute('SELECT canonical FROM play_events').fetchone()[0])['track']['artist'] == 'Canonical Artist'


def test_artist_hints_are_private_and_ambiguous_names_never_chosen(lab):
    one = '11111111-1111-4111-8111-111111111111'
    two = '22222222-2222-4222-8222-222222222222'
    def ranking():
        return {'items': [{'item': {'name': 'Artist', 'musicbrainz_id': None, 'listen_count': 4}}]}
    with store.connection(write=True) as c:
        artist_ids.remember(c, 'alice', {'artist': 'Artist', 'artist_mbids': [one]})
        artist_ids.remember(c, 'bob', {'artist': 'Artist', 'artist_mbids': [two]})
        assert artist_ids.supplement(c, 'alice', ranking())['items'][0]['item']['musicbrainz_id'] == one
        assert artist_ids.supplement(c, 'bob', ranking())['items'][0]['item']['musicbrainz_id'] == two
        artist_ids.remember(c, 'alice', {'artist': 'Artist', 'artist_mbids': [two]})
        assert artist_ids.supplement(c, 'alice', ranking())['items'][0]['item']['musicbrainz_id'] is None


def test_link_tokens_and_history_bridge_are_user_scoped(lab, transport, monkeypatch):
    async def profile(user):
        discovery_profile.init()
        return [{"name":user+" seed","mbid":"11111111-1111-4111-8111-111111111111","status":"identified"}]
    monkeypatch.setattr(discovery_profile,"profile",profile)
    client, _ = lab
    calls = []
    def upstream(request):
        calls.append(request)
        assert request.url.host == 'aurral'
        if request.url.path == '/api/auth/login':
            name = json.loads(request.content)['username']
            return httpx.Response(200, json={'user': {'id': 1 if name == 'alice' else 2}, 'token': name + '-session'})
        if request.url.path == '/api/discover/feedback':
            return httpx.Response(200, json={'feedback': []})
        token = request.headers['Authorization']
        name = token.removeprefix('Bearer ').removesuffix('-session')
        if request.method == 'PATCH':
            assert json.loads(request.content) == {'koito': 'http://music:8001/history/' + name[0] * 43,
                                                  'lastfm': None, 'listenbrainz': None}
            return httpx.Response(200, json={'success': True})
        return httpx.Response(200, json={'artists': [{'name': name + ' artist', 'secret': 'not-for-client'}]})
    transport(upstream)
    for name in ('alice', 'bob'):
        client.as_user(name)
        assert client.post('/api/integrations/aurral', json={'username': name, 'password': 'fictional'}).status_code == 200
        result = client.get('/api/discover').json()
        assert result['artists'][0]['name'] == name + ' artist'
        assert 'secret' not in json.dumps(result)
    client.as_user('alice')
    assert 'bob artist' not in client.get('/api/discover/history').text
    assert client.post('/api/integrations/aurral', json={'username': 'bob', 'password': 'fictional'}).status_code == 403
    assert integrations.aurral_token('alice') == 'alice-session'
    with store.connection() as c:
        assert all('-session' not in r[0] for r in c.execute('SELECT token FROM credentials'))
    assert all('private-koito-token' not in r.content.decode() for r in calls)


def test_bridge_is_read_only_and_does_not_reveal_other_user(lab, transport):
    def upstream(request):
        assert request.url.host == 'koito-alice'
        assert request.headers['Authorization'] == 'Token alice-private-koito-token'
        assert request.url.path == '/apis/web/v1/top/artists'
        return httpx.Response(200, json={'items': [{'name': 'Alice artist'}]})
    transport(upstream)
    client = TestClient(internal_main.app)
    path = '/history/' + 'a' * 43 + '/apis/web/v1/top/artists'
    assert client.get(path).json()['items'][0]['name'] == 'Alice artist'
    assert client.get('/history/alice/apis/web/v1/top/artists').status_code == 404
    assert client.get(path, params={'page': 100}).status_code == 422
    assert client.post(path, json=event()).status_code == 405
    assert client.get('/history/' + 'a' * 43 + '/apis/web/v1/top/tracks').status_code == 404
    assert client.get('/api/listening/top/artists').status_code == 404


@pytest.mark.parametrize('field,value', [('koito_url', 'http://koito-alice'), ('aurral_user_id', 1), ('bridge_key', 'a' * 43)])
def test_configuration_prevents_shared_private_integrations(lab, field, value):
    _, path = lab
    data = json.loads(path.read_text())
    data['users']['bob'][field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(RuntimeError):
        integrations.configuration()


def test_flows_are_filtered_even_if_upstream_admin_can_see_other_users(lab, monkeypatch):
    client, _ = lab
    async def upstream(*args, **kw):
        return {'flows': [{'id': 'alice-flow', 'ownerUserId': 1}, {'id': 'bob-flow', 'ownerUserId': 2}]}
    monkeypatch.setattr(integrations, 'aurral_request', upstream)
    assert len(client.get('/api/discover/flows').json()['flows']) == 1
    assert client.get('/api/discover/flows/bob-flow').status_code == 404


def test_listens_threshold_idempotency_conflicts_and_isolation(lab):
    client, _ = lab
    item = event()
    assert client.post('/api/listening/events', json={**item, 'listened_seconds': 99}).status_code == 422
    assert client.post('/api/listening/events', json=item).json() == {'accepted': True, 'duplicate': False}
    assert client.post('/api/listening/events', json=item).json()['duplicate'] is True
    assert client.post('/api/listening/events', json={**item, 'listened_seconds': 101}).status_code == 409
    client.as_user('bob')
    assert client.get('/api/listening/status').json() == {'delivery': {}}
    assert client.post('/api/listening/events', json=item).json()['duplicate'] is False
    client.as_user('alice')
    assert client.get('/api/listening/status').json() == {'delivery': {'pending': 1}}


@pytest.mark.parametrize('changes', [ {'listened_seconds': 0}, {'started_at': int(time.time()) + 10},
    {'started_at': int(time.time()) - 100 * 86400}, {'started_at': int(time.time()) - 5}])
def test_invalid_listening_times_rejected(lab, changes):
    client, _ = lab
    assert client.post('/api/listening/events', json=event(**changes)).status_code == 422


def test_retry_preserves_event_and_never_resets_another_user(lab):
    client, _ = lab
    item = event()
    for name in ('alice', 'bob'):
        client.as_user(name)
        assert client.post('/api/listening/events', json=item).status_code == 202
    with store.connection(write=True) as c:
        c.execute("UPDATE outbox SET state='blocked'")
    client.as_user('alice')
    assert client.post('/api/listening/retry').json() == {'queued': 1}
    assert client.post('/api/listening/retry').json() == {'queued': 0}
    assert client.post('/api/listening/events', json=item).json()['duplicate']
    client.as_user('bob')
    assert client.get('/api/listening/status').json() == {'delivery': {'blocked': 1}}


def test_outbox_delivers_private_credentials_and_recovers_timeout(lab, transport):
    client, _ = lab
    sent = []
    def upstream(request):
        sent.append((request.url.host, request.headers['Authorization'], json.loads(request.content)))
        if len(sent) == 1:
            raise httpx.ReadTimeout('lost response', request=request)
        return httpx.Response(200, json={'status': 'ok'})
    transport(upstream)
    item = event()
    client.post('/api/listening/events', json=item)
    asyncio.run(listening.deliver_pending())
    assert client.get('/api/listening/status').json() == {'delivery': {'pending': 1}}
    with store.connection(write=True) as c:
        c.execute('UPDATE outbox SET next_try=0')
    store.init()
    listening.recover()
    asyncio.run(listening.deliver_pending())
    asyncio.run(listening.deliver_pending())
    assert len(sent) == 2 and sent[0] == sent[1]
    assert sent[0][0:2] == ('koito-alice', 'Token alice-private-koito-token')
    assert sent[0][2]['payload'][0]['listened_at'] == item['started_at']
    assert client.get('/api/listening/status').json() == {'delivery': {'sent': 1}}
    client.as_user('bob')
    client.post('/api/listening/events', json=event())
    asyncio.run(listening.deliver_pending())
    assert sent[2][0:2] == ('koito-bob', 'Token bob-private-koito-token')


def test_upstream_redirect_and_errors_are_not_forwarded(lab, transport):
    transport(lambda req: httpx.Response(302, headers={'Location': 'https://third-party/secret'}))
    with pytest.raises(HTTPException) as error:
        asyncio.run(integrations.koito_read('alice'))
    assert error.value.status_code == 502
    assert 'secret' not in str(error.value)


def test_failed_history_link_does_not_persist_a_token(lab, transport):
    client, _ = lab
    def upstream(req):
        if req.url.path.endswith('login'):
            return httpx.Response(200, json={'user': {'id': 1}, 'token': 'never-save'})
        return httpx.Response(503, json={'debug': 'private internals'})
    transport(upstream)
    response = client.post('/api/integrations/aurral', json={'username': 'alice', 'password': 'fictional'})
    assert response.status_code == 502 and 'private' not in response.text
    with store.connection() as c:
        assert c.execute('SELECT count(*) FROM credentials').fetchone()[0] == 0


async def fake_personal(user):
    return {"version":1,"state":"ready","artists":[{"name":"Artist","sourceArtist":"Seed","provenance":"similar_to_identified_seed","seeds":[{"name":"Seed"}]}],
            "seeds":[{"name":"Seed","mbid":"11111111-1111-4111-8111-111111111111","status":"identified"}]}


def test_weekly_uses_private_scheduled_flow_without_downloads(lab, monkeypatch):
    monkeypatch.setattr(discovery_profile,'recommendations',fake_personal)
    client, _ = lab
    calls, created = [], []
    async def upstream(user, path, method='GET', body=None):
        calls.append((user, path, method, body))
        if path.endswith('/status'):
            return {'flows': created}
        if path.endswith('/flows'):
            assert body['autoDownload'] is False and body['mix']['trending']==0 and body['mix']['focus']==100
            assert body['relatedArtists']==['11111111-1111-4111-8111-111111111111', 'Seed'] and 'templateId' not in body
            created.append({'id': 'own-flow', 'name': body['name'], 'ownerUserId': 1, 'autoDownload': False})
            return {'flow': created[0]}
        if path.endswith('/enabled'):
            assert method=='PUT' and body=={'enabled':True}
            created[0]['enabled']=True
            return {'enabled':True}
        if method=='PUT':
            assert path=='/api/playlists/flows/own-flow' and body['mix']['focus']==100
            return {'success':True}
        assert path == '/api/playlists/start/own-flow'
        return {'queued': True}
    monkeypatch.setattr(integrations, 'aurral_request', upstream)
    assert client.post('/api/discover/weekly').json()['created'] is True
    assert client.post('/api/discover/weekly').json()['created'] is False
    assert sum(path.endswith('/enabled') for _, path, _, _ in calls) == 1
    assert not any('/start/' in path for _,path,_,_ in calls)
    created[0]['autoDownload'] = True
    assert client.post('/api/discover/weekly').status_code == 409


def test_real_aurral_job_units_and_private_refresh(lab, monkeypatch):
    monkeypatch.setattr(discovery_profile,'recommendations',fake_personal)
    client, _ = lab
    calls = []
    async def upstream(user, path, method='GET', body=None):
        calls.append(path)
        if path.endswith('/status'):
            return {'flows': [{'id': 'own', 'ownerUserId': 1, 'autoDownload': False}]}
        if '/jobs/' in path:
            return [{'trackName': 'Original', 'artistName': 'Artist', 'durationMs': 34000, 'finalPath': '/secret'},
                    {'trackName': 'Malformed', 'durationMs': 'NaN'}]
        if method=='PUT':
            assert path=='/api/playlists/flows/own' and body['mix']['trending']==0
            return {'success':True}
        assert path == '/api/playlists/start/own' and body == {'limit': 30}
        return {'queued': True}
    monkeypatch.setattr(integrations, 'aurral_request', upstream)
    result = client.get('/api/discover/flows/own').json()
    assert len(result['tracks']) == 1 and result['tracks'][0]['duration'] == 34
    assert 'secret' not in json.dumps(result)
    assert client.post('/api/discover/flows/own/refresh').status_code == 200
    assert client.post('/api/discover/flows/own/refresh').status_code == 429
    client.as_user('bob')
    assert client.post('/api/discover/flows/own/refresh').status_code == 404
    assert calls.count('/api/playlists/start/own') == 1


def test_weekly_without_identified_seeds_cannot_fall_back_to_popular(lab, monkeypatch):
    client, _ = lab
    async def empty(user):
        return {'artists': [], 'seeds': [], 'state': 'insufficient_profile'}
    async def forbidden(*args, **kwargs):
        raise AssertionError('must not create or regenerate a popular flow')
    monkeypatch.setattr(discovery_profile, 'recommendations', empty)
    monkeypatch.setattr(integrations, 'aurral_request', forbidden)
    assert client.post('/api/discover/weekly').status_code == 409


def test_refresh_preserves_custom_flow_manual_configuration(lab, monkeypatch):
    client, _ = lab
    calls = []
    async def upstream(user, path, method='GET', body=None):
        calls.append((path, method))
        if path.endswith('/status'):
            return {'flows': [{'id': 'custom', 'name': 'Manual choices', 'ownerUserId': 1, 'autoDownload': False}]}
        assert path == '/api/playlists/start/custom' and method == 'POST'
        return {'queued': True}
    async def forbidden(user):
        raise AssertionError('custom seed decisions must remain intact')
    monkeypatch.setattr(integrations, 'aurral_request', upstream)
    monkeypatch.setattr(discovery_profile, 'recommendations', forbidden)
    assert client.post('/api/discover/flows/custom/refresh').status_code == 200
    assert all(method != 'PUT' for _, method in calls)


def test_flow_keeps_recordings_aurral_ties_to_an_identified_seed_and_drops_the_rest(lab, monkeypatch):
    seed = 'a466063b-24a6-4235-bc95-352c93d8ce47'
    async def personal(user):
        return {'state': 'ready', 'seeds': [{'name': 'Semilla', 'mbid': seed, 'status': 'identified'},
                                            {'name': 'Dudosa', 'mbid': None, 'status': 'unresolved'}],
                'artists': [{'name': 'Listada', 'seeds': [{'name': 'Semilla', 'mbid': seed}]}]}
    blocked = {'value': [{'action': 'block_artist', 'artistName': 'Vetada'}]}
    async def upstream(user, path, method='GET', body=None):
        if path.endswith('/status'):
            return {'flows': [{'id': 'own', 'ownerUserId': 1, 'autoDownload': False}]}
        if path == '/api/discover/feedback':
            if blocked['value'] is None:
                raise HTTPException(502, 'down')
            return {'feedback': blocked['value']}
        assert '/jobs/' in path
        return [{'trackName': 'A', 'artistName': 'Listada', 'reason': 'x'},
                {'trackName': 'B', 'artistName': 'Semilla', 'reason': 'Similar to ' + seed},
                {'trackName': 'C', 'artistName': 'Lejana', 'reason': 'Similar to ' + seed},
                {'trackName': 'D', 'artistName': 'Vetada', 'reason': 'Similar to ' + seed},
                {'trackName': 'E', 'artistName': 'Tendencia', 'reason': 'Trending'},
                {'trackName': 'F', 'artistName': 'Otra', 'reason': 'Similar to 3aa9e7cd-fe96-4fea-b200-19beeea963c7'},
                {'trackName': 'G', 'artistName': 'Dudosa', 'reason': 'x'},
                {'trackName': 'H', 'artistName': 'Cercana', 'reason': 'Similar to Semilla'}]
    monkeypatch.setattr(discovery_profile, 'recommendations', personal)
    monkeypatch.setattr(integrations, 'aurral_request', upstream)
    client, _ = lab
    result = client.get('/api/discover/flows/own').json()
    # Aurral names the seed as it was given: its MBID or its name.
    assert [t['title'] for t in result['tracks']] == ['A', 'B', 'C', 'H']
    assert result['proposed'] == 8 and result['excludedBy'] == {'not_personal': 3, 'blocked': 1, 'invalid': 0}
    # Unknown exclusions: only the vetted artists remain.
    blocked['value'] = None
    assert [t['title'] for t in client.get('/api/discover/flows/own').json()['tracks']] == ['A', 'B']


def test_automatic_aurral_link_respects_origin_binding_and_explicit_unlink(lab, transport, monkeypatch):
    client, _ = lab
    calls = []
    def upstream(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"user": {"id": 1}, "token": "alice-token"})
        return httpx.Response(200, json={})
    transport(upstream)
    def login(user):
        asyncio.run(integrations.link_on_login(user, user, "fictional"))
    monkeypatch.setenv("MUSIC_AURRAL_LOGIN_ORIGIN", "http://unrelated")
    login("alice")
    assert not calls
    monkeypatch.setenv("MUSIC_AURRAL_LOGIN_ORIGIN", "http://aurral")
    login("alice")
    login("alice")
    assert len(calls) == 2 and integrations.aurral_token("alice") == "alice-token"
    login("bob")
    with pytest.raises(HTTPException):
        integrations.aurral_token("bob")
    assert client.delete("/api/integrations/aurral").is_success
    before = len(calls)
    login("alice")
    assert len(calls) == before
