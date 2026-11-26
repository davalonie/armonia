"""An album is one album: collaborators belong to their song, not to the album's identity.

Navidrome groups by album artist + album title, so these tests pin what is written to
the files and what reaches the tagger from each import source. All names are fictitious.
"""
import asyncio
import shutil
import subprocess

import pytest
from mutagen import File

from routes import import_batch, import_playlist
from services import spotify_client, tagger_service, ytdlp_service

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg unavailable")


def audio(tmp_path, name):
    path = tmp_path / name
    codec = {"m4a": ["-c:a", "aac"], "mp3": ["-c:a", "libmp3lame"], "opus": ["-c:a", "libopus"], "flac": []}[name.rsplit(".", 1)[1]]
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3",
                    *codec, str(path)], check=True)
    return str(path)


def tags(path):
    found = File(path, easy=True)
    return {key: list(found.get(key) or []) for key in ("artist", "artists", "albumartist", "album", "title")}


def album_key(path):
    """What makes two files the same album for Navidrome when there are no MusicBrainz ids."""
    found = tags(path)
    return found["albumartist"][0].casefold(), found["album"][0].casefold()


@needs_ffmpeg
@pytest.mark.parametrize("extension", ["m4a", "mp3", "opus", "flac"])
def test_a_collaboration_stays_in_its_album_and_keeps_its_performers(tmp_path, extension):
    alone = audio(tmp_path, "alone." + extension)
    shared = audio(tmp_path, "shared." + extension)
    tagger_service.tag(alone, "Banda Ficticia", "Intro", "Disco de Prueba", ["Banda Ficticia"])
    tagger_service.tag(shared, "Banda Ficticia, Invitada Uno", "Dueto", "Disco de Prueba", ["Banda Ficticia", "Invitada Uno"])
    assert album_key(alone) == album_key(shared) == ("banda ficticia", "disco de prueba")
    found = tags(shared)
    assert found["artist"] == ["Banda Ficticia, Invitada Uno"]  # the text shown keeps every collaborator
    assert found["artists"] == ["Banda Ficticia", "Invitada Uno"]  # and each one is an artist of this song
    assert tags(alone)["artists"] == []


@needs_ffmpeg
def test_two_editions_and_two_owners_of_the_same_title_are_not_merged(tmp_path):
    files = [audio(tmp_path, f"{i}.m4a") for i in range(4)]
    tagger_service.tag(files[0], "Banda Ficticia", "Tema", "Disco de Prueba", ["Banda Ficticia"])
    tagger_service.tag(files[1], "Banda Ficticia", "Tema", "Disco de Prueba (Deluxe)", ["Banda Ficticia"])
    tagger_service.tag(files[2], "Banda Ficticia", "Tema", "Disco de Prueba (En directo)", ["Banda Ficticia"])
    tagger_service.tag(files[3], "Otro Grupo", "Tema", "Disco de Prueba", ["Otro Grupo"])
    assert len({album_key(path) for path in files}) == 4


@needs_ffmpeg
def test_a_name_with_commas_or_ampersand_is_one_artist(tmp_path):
    free, listed, group = (audio(tmp_path, name) for name in ("free.m4a", "listed.m4a", "group.m4a"))
    # Free text, as typed or as a search result gives it: never split.
    tagger_service.tag(free, "Trío Uno, Dos & Tres", "Tema", "Disco")
    assert tags(free)["albumartist"] == ["Trío Uno, Dos & Tres"] and tags(free)["artists"] == []
    # A structured list keeps the comma inside the name.
    tagger_service.tag(listed, "Trío Uno, Dos & Tres, Invitada", "Tema", "Disco", ["Trío Uno, Dos & Tres", "Invitada"])
    assert tags(listed)["albumartist"] == ["Trío Uno, Dos & Tres"]
    assert tags(listed)["artists"] == ["Trío Uno, Dos & Tres", "Invitada"]
    tagger_service.tag(group, "Ana y Luis", "Tema", "Disco", ["Ana y Luis"])
    assert tags(group)["albumartist"] == ["Ana y Luis"]


@needs_ffmpeg
def test_the_album_artist_the_source_states_wins(tmp_path):
    first, second = audio(tmp_path, "a.m4a"), audio(tmp_path, "b.m4a")
    tagger_service.tag(first, "Solista A", "Uno", "Recopilatorio", ["Solista A"], "Varios Artistas")
    tagger_service.tag(second, "Solista B, Solista C", "Dos", "Recopilatorio", ["Solista B", "Solista C"], "Varios Artistas")
    assert album_key(first) == album_key(second) == ("varios artistas", "recopilatorio")


def test_album_artist_rule_without_files():
    assert tagger_service.album_artist_for("A, B", ["A", "B"]) == "A"
    assert tagger_service.album_artist_for("A, B") == "A, B"
    assert tagger_service.album_artist_for("A, B", [], "  ") == "A, B"
    assert tagger_service.album_artist_for("A, B", ["", "  ", "B"]) == "B"
    assert tagger_service.album_artist_for("A", ["A"], "Dueña") == "Dueña"
    assert tagger_service.clean_artists(["A", "A", " B ", None, 3]) == ["A", "B"]
    assert tagger_service.clean_artists("A, B") == []  # a string is not a list of names


def test_an_owner_export_keeps_each_performer_and_the_album_artist():
    text = ('Track URI,Track Name,Album Name,Artist Name(s),Album Artist Name(s),Duration (ms)\n'
            'spotify:track:1,Dueto,Disco de Prueba,"Banda Ficticia, Invitada Uno",Banda Ficticia,200000\n'
            'spotify:track:2,Tema,Otro Disco,"Trío Uno\\, Dos & Tres, Invitada",,180000\n'
            'spotify:track:3,Viejo,Disco Antiguo,Solista A;Solista B,,170000\n')
    first, second, third = spotify_client.parse_export(text, "Lista")["tracks"]
    assert first["artist"] == "Banda Ficticia, Invitada Uno" and first["artists"] == ["Banda Ficticia", "Invitada Uno"]
    assert first["album_artist"] == "Banda Ficticia"
    assert second["artists"] == ["Trío Uno, Dos & Tres", "Invitada"] and second["album_artist"] is None
    assert third["artists"] == ["Solista A", "Solista B"]
    # "Artista - Titulo" lines give no list: nothing is guessed from the text.
    plain = spotify_client.parse_export("Trío Uno, Dos & Tres - Tema\n", "Lista")["tracks"][0]
    assert "artists" not in plain and plain["artist"] == "Trío Uno, Dos & Tres"


def test_the_metadata_api_and_the_browser_sign_in_keep_the_same_information():
    track = spotify_client._track({
        "name": "Dueto", "duration_ms": 200000, "uri": "spotify:track:1",
        "artists": [{"name": "Banda Ficticia"}, {"name": "Invitada Uno"}],
        "album": {"name": "Disco de Prueba", "artists": [{"name": "Banda Ficticia"}]},
    }, 0)
    assert track["artists"] == ["Banda Ficticia", "Invitada Uno"] and track["album_artist"] == "Banda Ficticia"
    assert track["artist"] == "Banda Ficticia, Invitada Uno" and track["album"] == "Disco de Prueba"
    embed = spotify_client._track({"title": "Dueto", "duration": 200000, "subtitle": "Banda Ficticia, Invitada Uno"}, 0, embed=True)
    assert embed["artists"] == [] and embed["album_artist"] is None  # the public view gives only text

    row = import_batch.SourceTrack(title="Dueto", artist="Banda Ficticia, Invitada Uno", album="Disco de Prueba",
                                   artists=["Banda Ficticia", "Invitada Uno"], albumArtist="Banda Ficticia")
    assert row.artists == ["Banda Ficticia", "Invitada Uno"] and row.albumArtist == "Banda Ficticia"
    assert import_batch.SourceTrack(title="x", artist="y").artists == []  # older clients keep working


def test_an_import_hands_the_list_and_the_album_artist_to_the_download(monkeypatch):
    seen = {}

    async def limited(video, artist, title, source, **options):
        seen.update(options, artist=artist)
        return "/fixture/audio.m4a"

    monkeypatch.setattr(ytdlp_service, "download_limited", limited)
    asyncio.run(import_playlist._download_with_retry(
        "abcdefghijk", "Banda Ficticia, Invitada Uno", "Dueto", "/fixture", {}, "Disco de Prueba",
        artists=["Banda Ficticia", "Invitada Uno"], album_artist="Banda Ficticia"))
    assert seen["artist"] == "Banda Ficticia, Invitada Uno" and seen["album"] == "Disco de Prueba"
    assert seen["artists"] == ["Banda Ficticia", "Invitada Uno"] and seen["album_artist"] == "Banda Ficticia"
