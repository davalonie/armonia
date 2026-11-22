import pytest

from homelab import matcher
from homelab.models import Track


def song(**changes):
    return Track(**(dict(source="youtube", source_id="fixture0001", title="Get Off The World",
                         artist="Denom, Bluesproders", album="Get Off The World", duration=205) | changes))


def test_spacing_in_secondary_credit_is_supported_by_unchanged_primary_and_recording():
    wanted = {"title": "Get Off The World", "artist": "Denom, Blues Proders", "duration": 204.666,
              "album": "Get Off The World - Pa' Bailar Llorando"}
    ranked = matcher.rank(wanted, [song()])
    assert ranked["selected"] and ranked["candidates"][0]["artist_spacing"]
    assert ranked["candidates"][0]["score"] == 90
    assert not ranked["candidates"][0]["reasons"]


@pytest.mark.parametrize("wanted_artist,candidate_artist", [
    ("Denom, Blues, Proders", "Denom, Bluesproders"),  # Two people must not become one.
    ("Artist, DJ X", "Artist, DJX"),  # Too short to disambiguate reliably.
    ("Blue Sproders", "Bluesproders"),  # No independent primary credit anchor.
    ("Carrion GodBle$$, Saske", "Carrion, Saske"),  # A real alias is not whitespace.
    ("Denom, Blues Proders", "Another, Bluesproders"),
])
def test_spacing_does_not_alias_people_or_remove_words(wanted_artist, candidate_artist):
    wanted = {"title": "Get Off The World", "artist": wanted_artist, "duration": 205}
    assert matcher.rank(wanted, [song(artist=candidate_artist)])["selected"] is None


@pytest.mark.parametrize("changes", [{"title": "Get Off The World (Live)"}, {"duration": 210},
                                     {"title": "Get Off The World (Remix)"}, {"isrc": "ESAAA2600002"}])
def test_spacing_cannot_bypass_version_duration_or_identifier_conflict(changes):
    wanted = {"title": "Get Off The World", "artist": "Denom, Blues Proders", "duration": 205,
              "isrc": "ESAAA2600001"}
    assert matcher.rank(wanted, [song(**changes)])["selected"] is None


@pytest.mark.parametrize("delta", [-2, -1, 0.697, 1, 2])
def test_cebo_video_feat_and_small_duration_variation_are_not_rejected(delta):
    wanted = {"title": "Cebo Video", "artist": "Ergo Pro, Ill Pekeño, Victor Rutty, Rober del Pyro, DJ Kaef",
              "duration": 237.303, "album": "Cebo Video"}
    found = song(title="Cebo Video (feat. Victor Rutty, Rober del Pyro & DJ Kaef)",
                 artist="Ergo Pro, Ill Pekeño", album="Cebo Video", duration=237.303 + delta)
    assert matcher.rank(wanted, [found])["selected"] is not None


def test_same_source_id_is_deduplicated_but_distinct_audio_sources_remain_explained_tie():
    wanted = {"title": "Treneros Viajeros", "artist": "Victor Rutty", "duration": 184.5,
              "album": "Generación Perdida (La Mixtape)"}
    first = song(title=wanted["title"], artist=wanted["artist"], album=wanted["album"], duration=185)
    same = matcher.rank(wanted, [first, first.model_copy()])
    assert same["selected"] and len(same["candidates"]) == 1
    second = first.model_copy(update={"source_id": "fixture0002"})
    result = matcher.rank(wanted, [first, second])
    assert result["selected"] is None
    assert len(result["candidates"]) == 2
    assert [c["score"] for c in result["candidates"]] == [100, 100]
    assert result["choiceReason"] == "multiple_compatible_sources"
