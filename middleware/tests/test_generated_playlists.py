import asyncio

import pytest
from fastapi import HTTPException

import db
from homelab import discovery_profile, store
from homelab import generated_playlists as g
from routes import discover
from routes.library import RecentPlaylist, recent_playlists, remember_playlist
from services import navidrome_client, ytdlp_service

SEED = "a466063b-24a6-4235-bc95-352c93d8ce47"
OTHER = "3aa9e7cd-fe96-4fea-b200-19beeea963c7"


def video(n):
    return f"vid{n:08d}"


class Lab:
    def __init__(self):
        self.flow = [{"title": "Uno", "artist": "Ana", "album": "", "duration": 200.0},
                     {"title": "Dos", "artist": "Ana", "album": "", "duration": None},
                     {"title": "Sin fuente", "artist": "Nadie", "album": "", "duration": None}]
        self.local = [{"id": "nd1", "title": "Uno", "artist": "Ana", "album": "Disco", "duration": 201}]
        self.external = {"Ana Dos": [
            {"videoId": video(1), "title": "Dos (Live)", "channel": "Ana", "duration": 210, "thumbnail": "https://img/live"},
            {"videoId": video(2), "title": "Dos", "channel": "Ana", "duration": 190, "thumbnail": "https://img/dos"}]}
        self.personal = {"state": "ready", "seeds": [{"name": "Semilla", "mbid": SEED, "status": "identified"}],
                         "artists": [{"name": "Beta", "sourceArtist": "Semilla", "seeds": [{"name": "Semilla", "mbid": SEED}]},
                                     {"name": "Gamma", "sourceArtist": "Semilla", "seeds": [{"name": "Semilla", "mbid": SEED}]}]}
        self.flow_error = False
        self.searches = []


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "armonia.db")
    monkeypatch.setenv("MUSIC_YOUTUBE_CAPABILITIES", "stream")
    monkeypatch.delenv("MUSIC_SOURCES_FILE", raising=False)
    db.init_db()
    store.init()
    discovery_profile.init()
    g._tasks.clear()
    g._last_manual.clear()
    state = Lab()

    async def recommendations(user):
        return state.personal if user == "alice" else {"state": "insufficient_profile", "seeds": [], "artists": []}

    async def flow_tracks(flow, sess):
        if state.flow_error:
            raise HTTPException(502, "down")
        return {"tracks": state.flow}

    async def search_songs(query, *args, **kw):
        return [s for s in state.local if query.casefold() in (s["title"] + " " + s["artist"]).casefold()]

    def search(query, limit=10, source="youtube_music"):
        state.searches.append(query)
        return state.external.get(query, [])

    monkeypatch.setattr(discovery_profile, "recommendations", recommendations)
    monkeypatch.setattr(discover, "flow_tracks", flow_tracks)
    monkeypatch.setattr(navidrome_client, "search_songs", search_songs)
    monkeypatch.setattr(ytdlp_service, "search", search)
    monkeypatch.setattr(ytdlp_service, "search_artists", lambda name, limit: [
        {"channelId": "UC" + name, "name": name, "thumbnail": "https://img/" + name}, {"channelId": "UCx", "name": name + " Tribute"}])
    return state


def session(user):
    return db.get_session(db.create_session(user, "s", "t", user_id=user))


def activate(user):
    with store.connection(write=True) as c:
        c.execute("INSERT OR REPLACE INTO discovery_weekly VALUES (?,?,?)", (user, "flow-" + user, "{}"))


def run(user, sess, force=False):
    async def work():
        assert g.refresh(user, sess, force=force)
        await g._tasks[user]
    asyncio.run(work())


def ids(playlist):
    return [i["track"]["source_id"] for i in playlist["items"]]


def test_weekly_becomes_an_ordered_persistent_private_playlist(lab):
    alice, bob = session("alice"), session("bob")
    activate("alice")
    run("alice", alice)
    weekly = g.detail("alice", "weekly")
    # Library first, then the exact external version; the live take and the unmatched song are left out.
    assert ids(weekly) == ["nd1", video(2)]
    assert weekly["name"] == "Armonía semanal" and weekly["state"] == "ready" and weekly["updated"]
    assert weekly["items"][1]["cover"] == "https://img/dos"
    # Similar artists without a single available song do not produce an empty mix.
    assert [p["key"] for p in g.summaries("alice")] == ["weekly"]
    assert g.summaries("alice")[0]["covers"][0] == {"source": "navidrome", "source_id": "nd1", "cover": None}
    assert g.summaries("bob") == [] and g.artists("bob") == []
    with pytest.raises(HTTPException):
        g.detail("bob", "weekly")
    run("bob", bob)
    assert g.summaries("bob") == []  # No identified artists: no weekly list is offered.
    assert g.status("bob")["profile"] == "insufficient_profile"
    assert not g.refresh("alice", alice)  # Not due again: opening Inicio does not regenerate.


def test_failed_or_empty_refresh_keeps_the_previous_playlist(lab):
    alice = session("alice")
    activate("alice")
    run("alice", alice)
    before = g.detail("alice", "weekly")
    lab.flow_error = True
    run("alice", alice, force=True)
    after = g.detail("alice", "weekly")
    assert ids(after) == ids(before) and after["updated"] == before["updated"] and after["error"]
    lab.flow_error, lab.flow = False, []
    g._last_manual.clear()
    run("alice", alice, force=True)
    assert ids(g.detail("alice", "weekly")) == ids(before)
    with pytest.raises(HTTPException) as limited:
        g.refresh("alice", alice, force=True)
    assert limited.value.status_code == 429


def test_saved_copy_is_independent_of_later_refreshes(lab):
    alice = session("alice")
    activate("alice")
    run("alice", alice)
    copy = g.save_copy("alice", "weekly")
    assert copy["name"].startswith("Armonía semanal · ")
    lab.flow = [{"title": "Uno", "artist": "Ana", "album": "", "duration": 200.0}]
    run("alice", alice, force=True)
    assert ids(g.detail("alice", "weekly")) == ["nd1"]
    saved = store.playlist("alice", copy["id"])
    assert [i["track"]["source_id"] for i in saved["items"]] == ["nd1", video(2)]
    assert all("cover" not in i for i in saved["items"])
    with pytest.raises(HTTPException):
        store.playlist("bob", copy["id"])


def test_weekly_is_offered_inactive_only_when_it_can_be_activated(lab):
    alice = session("alice")
    run("alice", alice)
    weekly = g.detail("alice", "weekly")
    assert weekly["state"] == "inactive" and weekly["items"] == []


def test_external_songs_need_administrator_stream_permission(lab, monkeypatch):
    monkeypatch.setenv("MUSIC_YOUTUBE_CAPABILITIES", "")
    alice = session("alice")
    activate("alice")
    run("alice", alice)
    assert ids(g.detail("alice", "weekly")) == ["nd1"]


def test_similar_mix_interleaves_real_songs_of_similar_artists(lab):
    lab.local += [{"id": "b1", "title": "Beta uno", "artist": "Beta", "album": "", "duration": 100}]
    lab.external["Beta"] = [{"videoId": video(3), "title": "Beta dos", "channel": "Beta, Invitado", "duration": 100, "thumbnail": None},
                            {"videoId": video(4), "title": "Otra", "channel": "Beta Tributo", "duration": 100}]
    lab.external["Gamma"] = [{"videoId": video(5), "title": "Gamma uno", "channel": "Gamma", "duration": 100}]
    alice = session("alice")
    run("alice", alice)
    mix = g.detail("alice", "similar:" + SEED)
    assert mix["name"] == "Mix Semilla" and mix["kind"] == "similar"
    assert ids(mix) == ["b1", video(5), video(3)]
    assert mix["description"] == "Artistas similares a Semilla: Beta y Gamma."
    assert g.artists("alice") == [
        {"name": "Beta", "channelId": "UCBeta", "thumbnail": "https://img/Beta", "similarTo": "Semilla"},
        {"name": "Gamma", "channelId": "UCGamma", "thumbnail": "https://img/Gamma", "similarTo": "Semilla"}]
    # A seed that leaves the monthly ranking loses its mix; nothing else is touched.
    lab.personal = {**lab.personal, "seeds": [{"name": "Nueva", "mbid": OTHER, "status": "identified"}], "artists": []}
    run("alice", alice, force=True)
    assert [p["key"] for p in g.summaries("alice")] == ["weekly"]


def test_generated_playlist_enters_recents_only_for_its_owner(lab):
    alice, bob = session("alice"), session("bob")
    activate("alice")
    run("alice", alice)
    asyncio.run(remember_playlist(RecentPlaylist(kind="generated", id="weekly"), alice))
    recent = recent_playlists(alice, "web")["playlists"]
    assert recent[0]["name"] == "Armonía semanal" and recent[0]["covers"][0]["source_id"] == "nd1"
    assert recent_playlists(bob, "web") == {"playlists": []}
    assert recent_playlists(alice, None) == {"playlists": []}  # Older Android client: unknown kind withheld.
    assert recent_playlists(alice, None, "generated")["playlists"][0]["id"] == "weekly"
    with pytest.raises(HTTPException):
        asyncio.run(remember_playlist(RecentPlaylist(kind="generated", id="weekly"), bob))
    with pytest.raises(HTTPException):
        g.detail("alice", "similar:not-a-key")


def test_main_artist_only_proposals_resolve_to_the_collaboration_but_never_to_another_recording(lab):
    # Recommendation providers name the main artist only; the source lists every collaborator.
    lab.flow = [{"title": "Take Care", "artist": "Dirty", "album": "", "duration": None},
                {"title": "Isla (feat. Costa)", "artist": "Blas", "album": "", "duration": None},
                {"title": "Lo Real", "artist": "Hard", "album": "", "duration": None},
                {"title": "Dos Tomas", "artist": "Duo", "album": "", "duration": None},
                {"title": "Ajena", "artist": "Easy", "album": "", "duration": None}]
    lab.local = []
    lab.external = {
        "Dirty Take Care": [{"videoId": video(10), "title": "Take Care", "channel": "Dirty, mvrk, Danni", "duration": 189}],
        "Blas Isla (feat. Costa)": [{"videoId": video(11), "title": "Isla (feat. Costa)", "channel": "Blas, Ayax y Prok", "duration": 181}],
        # The remix shares title words and artists but is a different version.
        "Hard Lo Real": [{"videoId": video(12), "title": "Lo Real (Remix)", "channel": "Hard, Nik, Dualy", "duration": 225},
                         {"videoId": video(13), "title": "Lo Real", "channel": "Hard, Nik", "duration": 207}],
        # Two different recordings qualify equally: abstain instead of guessing.
        "Duo Dos Tomas": [{"videoId": video(14), "title": "Dos Tomas", "channel": "Duo, Uno", "duration": 150},
                          {"videoId": video(15), "title": "Dos Tomas", "channel": "Duo, Otro", "duration": 240}],
        # Same title where the proposed artist is only a guest, or absent: not the proposal.
        "Easy Ajena": [{"videoId": video(16), "title": "Ajena", "channel": "Otro, Easy", "duration": 100},
                       {"videoId": video(17), "title": "Ajena", "channel": "Eazy", "duration": 100}]}
    alice = session("alice")
    activate("alice")
    run("alice", alice)
    assert ids(g.detail("alice", "weekly")) == [video(10), video(11), video(13)]
    report = g.status("alice")["weekly"]
    assert (report["eligible"], report["external"], report["no_source"], report["listed"]) == (5, 3, 2, 3)
    # The next run reuses what was resolved instead of searching again.
    lab.searches.clear()
    g._last_manual.clear()
    run("alice", alice, force=True)
    assert not [q for q in lab.searches if q in ("Dirty Take Care", "Hard Lo Real")]
    assert g.status("alice")["weekly"]["reused"] == 3


def test_mix_lists_a_song_credited_to_two_similar_artists_once(lab):
    shared = {"id": "both", "title": "Juntos", "artist": "Beta, Gamma", "album": "", "duration": 100}
    lab.local += [shared]
    alice = session("alice")
    run("alice", alice)
    assert ids(g.detail("alice", "similar:" + SEED)) == ["both"]


def test_list_size_is_configurable_and_bounded(monkeypatch):
    assert g.size() == 30
    for value, expected in (("12", 12), ("500", 50), ("1", 10), ("x", 30)):
        monkeypatch.setenv("MUSIC_GENERATED_PLAYLIST_SIZE", value)
        assert g.size() == expected
