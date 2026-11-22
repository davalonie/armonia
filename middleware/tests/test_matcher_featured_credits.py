"""Credit placement changes, with no provider calls or acoustic assumptions."""
import pytest

from homelab import matcher
from homelab.models import Track


def candidate(title="Cara Norte (feat. DJ Kaef & Bombony Montana)", **changes):
    data = dict(source="youtube", source_id="fixture0001", title=title,
                artist="Victor Rutty, Rober del Pyro, Lone", duration=214)
    return Track(**(data | changes))


WANTED = {"title": "Cara Norte", "artist": "Victor Rutty, Rober del Pyro, Lone, DJ Kaef, Bombony Montana",
          "duration": 213}


@pytest.mark.parametrize("title", [
    "Cara Norte (feat. DJ Kaef & Bombony Montana)",
    "Cara Norte [ft. DJ Kaef & Bombony Montana]",
    "Cara Norte featuring DJ Kaef and Bombony Montana",
    "Cara Norte FEAT DJ Kaef y Bombony Montana",
    "Cara Norte (feat. DJ Kaef, Bombony Montana)",
    "Cara Norte (feat. DJ Kaef; Bombony Montana)",
])
def test_explicit_guests_in_title_match_separately_listed_artists(title):
    result = matcher.rank(WANTED, [candidate(title)])
    assert result["selected"] is not None
    assert result["candidates"][0]["credits"] == "equal"
    assert not result["candidates"][0]["reasons"]


def test_featured_credit_can_be_in_either_sources_title_or_artist_field():
    origin = {"title": "Cara Norte (ft. DJ Kaef & Bombony Montana)",
              "artist": "Victor Rutty, Rober del Pyro, Lone", "duration": 213}
    assert matcher.rank(origin, [candidate("Cara Norte", artist=WANTED["artist"])])["selected"]
    assert matcher.rank(WANTED, [candidate("Cara Norte", artist="Victor Rutty, Rober del Pyro, Lone feat. DJ Kaef & Bombony Montana")])["selected"]


@pytest.mark.parametrize("band", ["Simon & Garfunkel", "Earth Wind & Fire", "Ayax y Prok", "Florence and the Machine"])
def test_band_names_are_preserved_in_main_and_featured_credits(band):
    assert matcher.credits({"title": "Song", "artist": band})[1] == {matcher.normalized(band)}
    wanted = {"title": "Song", "artist": f"Fixture, {band}", "duration": 200}
    found = candidate(f"Song (feat. {band})", artist="Fixture", duration=200)
    assert matcher.rank(wanted, [found])["selected"]
    assert matcher.score(wanted, found)["credits"] == "equal"
    # No context-free fragmentation is used by continuation/recommendation callers.
    assert matcher.credits(found)[1] == {"fixture", matcher.normalized(band)}


def test_main_artist_ampersand_does_not_become_two_people():
    wanted = {"title": "Song", "artist": "Simon, Garfunkel", "duration": 200}
    assert matcher.rank(wanted, [candidate("Song", artist="Simon & Garfunkel", duration=200)])["selected"] is None


@pytest.mark.parametrize("title,changes", [
    ("Cara Norte (feat. DJ Kaef & Another Guest)", {}),
    ("Cara Norte (feat. DJ Kaef & Bombony Montana) (Live)", {}),
    ("Cara Norte (feat. DJ Kaef & Bombony Montana Remix)", {}),
    ("Cara Norte (feat. DJ Kaef & Bombony Montana)", {"duration": 240}),
    ("Cara Norte (feat. DJ Kaef & Bombony Montana)", {"artist": "Another Main Artist"}),
])
def test_credit_alignment_does_not_override_recording_evidence(title, changes):
    assert matcher.rank(WANTED, [candidate(title, **changes)])["selected"] is None


def test_equally_supported_candidates_still_need_a_choice():
    first = candidate()
    second = first.model_copy(update={"source_id": "fixture0002"})
    assert matcher.rank(WANTED, [first, second])["selected"] is None


def test_complete_known_band_credit_takes_precedence_over_component_names():
    known = {"simon garfunkel", "simon", "garfunkel"}
    assert matcher.credits({"title": "Song (feat. Simon & Garfunkel)", "artist": "Fixture"}, known)[1] == {
        "fixture", "simon garfunkel",
    }
