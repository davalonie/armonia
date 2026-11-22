"""Conservative recording matching. Ambiguous versions never auto-select."""
import re
import unicodedata
from difflib import SequenceMatcher

_MARKERS = {
    "live": r"\b(live|en directo|en vivo|concert)\b",
    "remix": r"\b(remix|mix|edit)\b",
    "cover": r"\b(cover|tribute)\b",
    "instrumental": r"\b(instrumental|karaoke)\b",
    "acoustic": r"\b(acoustic|acustic[ao]|unplugged)\b",
    "remaster": r"\b(remaster(?:ed)?|remasterizad[ao])\b",
    "rerecord": r"\b(re[ -]?recorded|taylor.s version|nueva version)\b",
}


def normalized(text):
    text = "".join(c for c in unicodedata.normalize("NFKD", text).casefold() if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def version(text):
    text = normalized(text)
    return {label for label, pattern in _MARKERS.items() if re.search(pattern, text)}



def _featured_credits(value, known_artists):
    """Split conjunctions only when another source explicitly lists every name.

    An ampersand is also part of band names. Preserve an exact complete credit
    before considering its parts, and never split the main artist field on it.
    Without corroboration, keep the ambiguous phrase as one credit.
    """
    whole = normalized(value)
    if whole in known_artists:
        return {whole}
    artists = set()
    for part in re.split(r"[,;]", value):
        name = normalized(part)
        if not name:
            continue
        separated = {normalized(a) for a in re.split(r"\s*&\s*|\s+(?:and|y)\s+", part, flags=re.I)}
        if name not in known_artists and len(separated) > 1 and separated <= known_artists:
            artists.update(separated)
        else:
            artists.add(name)
    return artists


def credits(obj, known_artists=()):
    """Only explicit feat./ft. credits move between title and artist fields.

    Compare complete sets, never aliases. Other version text survives. A caller
    comparing two sources may supply explicit credits to disambiguate feat lists.
    """
    known_artists = set(known_artists)
    get = obj.get if isinstance(obj, dict) else lambda k: getattr(obj, k, None)
    title, artist = get('title') or '', get('artist') or ''
    guests = []
    def featured(match):
        guests.append(match.group(1))
        return ''
    title = re.sub(r"[\[(]\s*(?:feat\.?|ft\.?|featuring)\s+([^()\[\]]+)[\])]", featured, title, flags=re.I)
    title = re.sub(r"\s+(?:feat\.?|ft\.?|featuring)\s+(.+)$", featured, title, flags=re.I)
    artist, *artist_guests = re.split(r"\s+(?:feat\.?|ft\.?|featuring)\s+", artist, flags=re.I)
    guests.extend(artist_guests)
    artists = {normalized(a) for a in re.split(r",", artist) if normalized(a)}
    for guest in guests:
        artists.update(_featured_credits(guest, known_artists))
    return normalized(title), artists


def primary(obj):
    """First listed artist: the only credit some providers supply."""
    get = obj.get if isinstance(obj, dict) else lambda k: getattr(obj, k, None)
    artist = re.sub(r"\s+(?:feat\.?|ft\.?|featuring)\s+", ",", get("artist") or "", flags=re.I)
    return normalized(artist.split(",")[0])


def _spacing_only_credits(wanted, candidate, left, right):
    """Corroborated spacing variants in collaborator names, not arbitrary aliases.

    Require an unchanged primary artist and an injective full credit mapping.
    In particular, never join two artists or remove words from a name.
    """
    if left == right or not primary(wanted) or primary(wanted) != primary(candidate):
        return False
    a, b = {name.replace(" ", ""): name for name in left}, {name.replace(" ", ""): name for name in right}
    if len(a) != len(left) or len(b) != len(right) or a.keys() != b.keys():
        return False
    return all(len(key) >= 6 for key in a if a[key] != b[key])


def _conjoined_credits(wanted, candidate, left, right):
    """Corroborate a joint artist credit without creating a global artist alias.

    A separate unchanged collaborator anchors the expansion. Every component
    must be explicitly listed on the other side, with no extras or collisions.
    Keep context-free credits/primary intact for recommendations and callers.
    """
    def expands(obj, original, other):
        get = obj.get if isinstance(obj, dict) else lambda k: getattr(obj, k, None)
        artist = re.split(r"\s+(?:feat\.?|ft\.?|featuring)\s+", get("artist") or "", maxsplit=1, flags=re.I)[0]
        for raw in artist.split(","):
            whole = normalized(raw)
            if whole not in original or whole in other:
                continue  # A complete matching band name always takes precedence.
            pieces = [normalized(part) for part in re.split(r"\s+(?:y|and|&)\s+", raw, flags=re.I)]
            parts, remainder = set(pieces), original - {whole}
            if (len(parts) > 1 and len(parts) == len(pieces) and "" not in parts
                    and remainder and not parts & remainder and parts <= other
                    and parts | remainder == other):
                return True
        return False

    return left != right and (expands(wanted, left, right) or expands(candidate, right, left))


def _garbled(wanted, candidate):
    """The same title with accented characters destroyed by a wrong text encoding at the source
    ("Inversión" published as "Inversi—n"). Same length, at most two positions differ, each one a
    non-ASCII character in the wanted title replaced by a non-letter or another non-ASCII
    character; at least six characters must agree, so short titles never qualify."""
    a, b = wanted.casefold().strip(), candidate.casefold().strip()
    if a == b or len(a) != len(b):
        return False
    differing = [(x, y) for x, y in zip(a, b, strict=True) if x != y]
    return (len(differing) <= 2 and len(a) - len(differing) >= 6
            and all(ord(x) > 127 and (ord(y) > 127 or not y.isalnum()) for x, y in differing))


def score(wanted, candidate):
    def get(obj, key):
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    wt, wa_credits = credits(wanted)
    ct, ca_credits = credits(candidate)
    # Move explicitly featured guests between fields without interpreting every
    # ampersand/conjunction in a band's name as an artist separator.
    wt, wa_credits = credits(wanted, ca_credits)
    ct, ca_credits = credits(candidate, wa_credits)
    t = SequenceMatcher(None, wt, ct).ratio()
    a = SequenceMatcher(None, ','.join(sorted(wa_credits)), ','.join(sorted(ca_credits))).ratio()
    reasons = []
    if not wt or not ct or not wa_credits or not ca_credits or 'unknown' in wa_credits | ca_credits:
        reasons.append("metadata missing")
    wanted_version = version((get(wanted, "title") or "") + " " + (get(wanted, "album") or ""))
    candidate_version = version((get(candidate, "title") or "") + " " + (get(candidate, "album") or ""))
    if wanted_version != candidate_version:
        reasons.append("different recording version")
    wd, cd = get(wanted, "duration"), get(candidate, "duration")
    close_duration = bool(wd and cd and abs(wd - cd) <= max(3, wd * .02))
    if wd and cd and not close_duration:
        reasons.append("duration differs")
    if not wd or not cd:
        reasons.append("duration unverified")
    spacing_match = (bool(wd and cd) and abs(wd - cd) <= 3 and t == 1
                     and wanted_version == candidate_version
                     and _spacing_only_credits(wanted, candidate, wa_credits, ca_credits))
    conjunction_match = (bool(wd and cd) and abs(wd - cd) <= 3 and t == 1
                         and wanted_version == candidate_version
                         and _conjoined_credits(wanted, candidate, wa_credits, ca_credits))
    if spacing_match or conjunction_match:
        a = 1
    if t != 1 or a != 1:
        reasons.append("title or artist is not exact enough")
    wa, ca = normalized(get(wanted, "album") or ""), normalized(get(candidate, "album") or "")
    value = t * 35 + a * 35 + (20 if close_duration else 0) + (10 if wa and wa == ca else 0)
    matching_id = False
    for ident in ("recording_mbid", "isrc"):
        x, y = get(wanted, ident), get(candidate, ident)
        if x and y and str(x).casefold() != str(y).casefold():
            reasons.append(f"conflicting {ident}")
        elif x and y:
            matching_id = True
            value = min(100, value + 10)
    if matching_id and t == 1 and close_duration and wa_credits & ca_credits:
        reasons = [r for r in reasons if r != "title or artist is not exact enough"]
    # Version labels do not identify the venue/remixer: require complete title.
    if wanted_version and (t != 1 or (wa and ca and wa != ca)):
        reasons.append("version detail differs")
    # Structured evidence for callers that may accept an incomplete credit list
    # (a provider naming only the main artist). It never clears a reason here.
    relation = "equal" if wa_credits == ca_credits or spacing_match or conjunction_match else (
        "subset" if (wa_credits <= ca_credits or ca_credits <= wa_credits)
        and primary(wanted) and primary(wanted) == primary(candidate) else "different")
    return {"score": round(value, 1), "reasons": reasons, "title_exact": bool(wt) and wt == ct, "credits": relation,
            "close_duration": close_duration,
            "artist_spacing": spacing_match,
            "artist_conjunction": conjunction_match,
            "title_garbled": _garbled(get(wanted, "title") or "", get(candidate, "title") or "")}


def rank(wanted, candidates):
    unique = {(t.source, t.source_id): t for t in candidates}
    ranked = sorted(({"track": t.model_dump(mode="json"), **score(wanted, t)} for t in unique.values()),
                    key=lambda x: x["score"], reverse=True)
    selected = None
    if ranked:
        top = ranked[0]
        # Only another candidate that could itself be accepted competes for the margin: a
        # runner-up with a different title ("Demons II") does not make "Demons" ambiguous.
        rivals = [c["score"] for c in ranked[1:] if not c["reasons"]]
        margin = top["score"] - rivals[0] if rivals else 100
        if top["score"] >= 90 and margin >= 10 and not top["reasons"]:
            selected = top["track"]
    if selected is None:
        selected = _collaboration(wanted, ranked)
    compatible = [c for c in ranked if not c["reasons"] and c["score"] >= 90]
    return {"selected": selected, "candidates": ranked, "needsChoice": selected is None,
            "choiceReason": "multiple_compatible_sources" if selected is None and len(compatible) > 1 else None}


def _collaboration(wanted, ranked):
    """Sources credit collaborators differently (one lists a guest the other omits).

    Text equality of the credit list is then impossible, but the recording is still
    identified by independent evidence: exact title, same version, same main artist, one
    credit list containing the other, and a duration equal within 1.5 s (tighter than the
    general tolerance). Only when exactly one candidate has that evidence; otherwise abstain.
    """
    get = wanted.get if isinstance(wanted, dict) else lambda k: getattr(wanted, k, None)
    duration = get("duration")
    if not duration:
        return None
    strong = [c for c in ranked if (c["title_exact"] or c["title_garbled"]) and c["credits"] in {"equal", "subset"}
              and c["track"].get("duration") and abs(c["track"]["duration"] - duration) <= 1.5
              and set(c["reasons"]) <= {"title or artist is not exact enough"}]
    if len(strong) != 1 or (strong[0]["credits"] != "subset" and not strong[0]["title_garbled"]):
        return None
    strong[0]["evidence"] = "garbled_title" if strong[0]["title_garbled"] else "collaborator_credits"
    return strong[0]["track"]
