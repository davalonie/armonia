"""Track number, disc number and date travel from the source to the file, and only when valid."""
import subprocess

import pytest
from mutagen import File as MutagenFile

from services import spotify_client, tagger_service


@pytest.fixture
def song(tmp_path):
    path = tmp_path / "song.m4a"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "aac", str(path)], check=True)
    return path


def read(path):
    tags = MutagenFile(str(path), easy=True)
    return {key: tags.get(key) for key in ("tracknumber", "discnumber", "date", "originaldate", "album", "albumartist")}


def test_only_plainly_valid_details_are_kept():
    clean = tagger_service.clean_details
    assert clean({"track": 7, "disc": 1, "date": "2019-03-08"}) == {"track": 7, "disc": 1, "date": "2019-03-08"}
    assert clean({"track": "12", "disc": " 2 ", "date": "1998"}) == {"track": 12, "disc": 2, "date": "1998"}
    assert clean({"track": 0, "disc": -1, "date": "0000"}) == {}
    assert clean({"track": 1000, "disc": 100, "date": "2019-13-01"}) == {}
    assert clean({"track": True, "date": "ayer"}) == {}
    assert clean({"track": 3.0, "date": 2019}) == {}
    assert clean(None) == {} and clean("7") == {}


def test_the_file_gets_its_position_and_year(song):
    tagger_service.tag(str(song), "Lúa Norte", "Bajamar", "Mareas", details={"track": 4, "disc": 1, "date": "2019-03-08"})
    tags = read(song)
    assert tags["tracknumber"][0].split("/")[0] == "4"
    assert tags["discnumber"][0].split("/")[0] == "1"
    assert tags["originaldate"] == ["2019-03-08"]
    assert tags["date"] is None, "DATE would split the album in Navidrome"
    assert tags["album"] == ["Mareas"] and tags["albumartist"] == ["Lúa Norte"]


def test_without_details_nothing_is_invented(song):
    tagger_service.tag(str(song), "Lúa Norte", "Bajamar", "Mareas")
    tags = read(song)
    assert tags["tracknumber"] is None and tags["discnumber"] is None
    assert tags["date"] is None and tags["originaldate"] is None


def test_the_export_file_columns_are_read():
    text = ("Track URI,Track Name,Album Name,Artist Name(s),Release Date,Duration (ms),Disc Number,Track Number,ISRC\n"
            "spotify:track:1,Bajamar,Mareas,Lúa Norte,2019-03-08,200000,1,4,XX0000000001\n"
            "spotify:track:2,Sin datos,Mareas,Lúa Norte,,200000,,,\n")
    tracks = spotify_client.parse_export(text, "mareas.csv")["tracks"]
    assert tracks[0]["details"] == {"track": 4, "disc": 1, "date": "2019-03-08"}
    assert tracks[1]["details"] == {}


def test_the_api_track_carries_them():
    track = spotify_client._track({
        "name": "Bajamar", "artists": [{"name": "Lúa Norte"}], "duration_ms": 200000, "track_number": 4, "disc_number": 1,
        "album": {"name": "Mareas", "artists": [{"name": "Lúa Norte"}], "release_date": "2019"},
    }, 0)
    assert track["details"] == {"track": 4, "disc": 1, "date": "2019"}
    assert spotify_client._track({"title": "Bajamar", "subtitle": "Lúa Norte", "duration": 200000}, 0, embed=True)["details"] == {}
