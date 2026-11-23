import asyncio

import pytest
from fastapi import HTTPException

import db
from homelab.models import Track
from routes.library import (
    RecentPlaylist,
    TrackPreference,
    recent_playlists,
    remember_playlist,
    set_track_preference,
    track_preferences,
)


def test_external_preferences_persist_and_are_private(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'db.sqlite')
    db.init_db()
    a=db.get_session(db.create_session('alice','s','t',user_id='alice'))
    b=db.get_session(db.create_session('bob','s','t',user_id='bob'))
    track=Track(source='youtube',source_id='abcdefghijk',title='Fixture',artist='Composer')
    set_track_preference(TrackPreference(track=track,favorite=True,rating=4),a)
    db.init_db()
    assert track_preferences(a)['items'][0]['rating']==4
    assert track_preferences(b)=={'items':[]}
    set_track_preference(TrackPreference(track=track,favorite=True,rating=0),a)
    assert track_preferences(a)['items'][0]['favorite']
    db.delete_session(a['id'])
    with pytest.raises(HTTPException):
        set_track_preference(TrackPreference(track=track),a)


def test_recent_playlist_records_only_explicit_playback_reports_and_owner(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'db.sqlite')
    db.init_db()
    from homelab import store
    store.init()
    a=db.get_session(db.create_session('alice','s','t',user_id='alice'))
    b=db.get_session(db.create_session('bob','s','t',user_id='bob'))
    async def owned(id,sess): return {'name':'Fixture','id':id}
    monkeypatch.setattr('routes.library.navidrome_client.owned_playlist',owned)
    assert recent_playlists(a)=={'playlists':[]}
    asyncio.run(remember_playlist(RecentPlaylist(kind='local',id='one'),a))
    asyncio.run(remember_playlist(RecentPlaylist(kind='local',id='two'),a))
    asyncio.run(remember_playlist(RecentPlaylist(kind='local',id='one'),a))
    assert [p['id'] for p in recent_playlists(a)['playlists']]==['one','two']
    assert recent_playlists(b)=={'playlists':[]}
