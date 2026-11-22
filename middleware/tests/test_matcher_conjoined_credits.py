"""Provider credit punctuation may differ; no context-free artist aliasing."""
import pytest

from homelab import matcher
from homelab.models import Track


def track(**changes):
    return Track(**(dict(source="youtube", source_id="fixture0001", title="Platos rotos",
                         artist="Natos, Waor, Recycled J", duration=223, album="Luna llena") | changes))


WANTED = {"title": "Platos rotos", "artist": "Natos y Waor, Recycled J", "duration": 222}


@pytest.mark.parametrize("connector", ["y", "Y", "and", "AND", "&"])
@pytest.mark.parametrize("reverse", [False, True])
def test_joint_credit_is_backed_by_complete_other_credits_and_unchanged_collaborator(connector, reverse):
    wanted = WANTED | {"artist": f"Natos {connector} Waor, Recycled J"}
    candidate = track()
    if reverse:
        wanted, candidate = candidate.model_dump(), track(**wanted)
    result = matcher.rank(wanted, [candidate])
    assert result["selected"] is not None
    score = result["candidates"][0]
    assert score["artist_conjunction"] and score["credits"] == "equal"
    assert score["score"] >= 90 and not score["reasons"]


@pytest.mark.parametrize("wanted_artist,candidate_artist", [
    ("Natos y Waor, Recycled J", "Natos, Recycled J"),
    ("Natos y Waor, Recycled J", "Waor, Recycled J"),
    ("Natos y Waor, Recycled J", "Natos, Waor"),
    ("Natos y Waor, Recycled J", "Natos, Waor, Recycled J, Otro"),
    ("Natos y Waor, Recycled J", "Natos, Waor, Otro"),
    ("Natos y Natos, Recycled J", "Natos, Recycled J"),
    ("Natos y Waor, Natos", "Natos, Waor"),
    ("Natos y Waor", "Natos, Waor"),  # No independent unchanged credit.
    ("Simon & Garfunkel", "Simon, Garfunkel"),
    ("Y&T, Fixture", "Y, T, Fixture"),  # No standalone conjunction.
    ("Ayax, Recycled J", "A, Ax, Recycled J"),
])
def test_conjunction_does_not_invent_credits_or_fragment_names(wanted_artist, candidate_artist):
    result = matcher.rank(WANTED | {"artist": wanted_artist}, [track(artist=candidate_artist)])
    assert result["selected"] is None
    assert not result["candidates"][0]["artist_conjunction"]


@pytest.mark.parametrize("changes", [
    {"title": "Platos rotos (Live)"}, {"title": "Platos rotos (Remix)"},
    {"title": "Otro título"}, {"duration": 226}, {"duration": None},
    {"artist": "Natos, Waor, Recycled Junior"},
    {"isrc": "ESAAA2600002"}, {"recording_mbid": "00000000-0000-0000-0000-000000000002"},
])
def test_recording_conflicts_still_block_automatic_selection(changes):
    wanted = WANTED | {"isrc": "ESAAA2600001", "recording_mbid": "00000000-0000-0000-0000-000000000001"}
    assert matcher.rank(wanted, [track(**changes)])["selected"] is None


def test_joint_artist_in_guest_position_and_missing_recording_evidence():
    wanted = WANTED | {"artist": "Recycled J, Natos y Waor"}
    assert matcher.rank(wanted, [track(artist="Recycled J, Natos, Waor")])["selected"]
    assert matcher.rank(wanted | {"duration": None}, [track()])["selected"] is None


def test_context_free_identity_and_candidate_ties_remain_unchanged():
    before = matcher.credits(WANTED)
    assert before[1] == {"natos y waor", "recycled j"}
    assert matcher.primary(WANTED) == "natos y waor"
    first = track()
    result = matcher.rank(WANTED, [first, first.model_copy(update={"source_id": "fixture0002"})])
    assert result["selected"] is None and result["choiceReason"] == "multiple_compatible_sources"
    assert matcher.credits(WANTED) == before
