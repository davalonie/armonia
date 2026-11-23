import re
from collections.abc import Callable, Iterable
from pathlib import Path

from mutagen import File as MutagenFile

DEFAULT_ALBUM = "Singles"


def _register_artists_key() -> None:
    """Teach mutagen's easy tags the multi-valued ARTISTS field that Navidrome reads."""
    from mutagen.easyid3 import EasyID3
    from mutagen.easymp4 import EasyMP4Tags

    if "artists" not in EasyID3.valid_keys:
        EasyID3.RegisterTXXXKey("artists", "ARTISTS")
    if "artists" not in EasyMP4Tags.Get:
        EasyMP4Tags.RegisterFreeformKey("artists", "ARTISTS")
    # EasyID3 already knows "originaldate" (TDOR); MP4 needs the freeform name Navidrome reads.
    if "originaldate" not in EasyMP4Tags.Get:
        EasyMP4Tags.RegisterFreeformKey("originaldate", "ORIGINALDATE")


_register_artists_key()


def clean_artists(artists) -> list[str]:
    """The names of a structured artist list, in order, without blanks or repeats."""
    names = []
    for name in artists if isinstance(artists, (list, tuple)) else ():
        name = name.strip() if isinstance(name, str) else ""
        if name and name not in names:
            names.append(name)
    return names


def album_artist_for(artist: str, artists=None, album_artist: str | None = None) -> str:
    """Who an album belongs to, which is what makes its songs group as one album.

    Navidrome identifies an album by album artist + title, so a collaboration tagged
    with all its performers as album artist becomes an album of its own. Use, in order:
    the album artist the source states; the first name of the *structured* list of
    performers; the artist text as written. Free text is never split on commas, "y"
    or "&": «Tyler, The Creator» and «Earth, Wind & Fire» are single names.
    """
    stated = (album_artist or "").strip()
    if stated:
        return stated
    names = clean_artists(artists)
    return names[0] if names else artist


def clean_details(details) -> dict:
    """Track number, disc number and date as the source states them, or nothing.

    Only what is plainly valid is kept: a position between 1 and 999, a disc between 1 and
    99, and a date written YYYY, YYYY-MM or YYYY-MM-DD from year 1000 on. Never a guess.
    """
    out = {}
    if not isinstance(details, dict):
        return out
    for key, top in (("track", 999), ("disc", 99)):
        value = details.get(key)
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        if type(value) is int and 1 <= value <= top:
            out[key] = value
    date = details.get("date")
    if isinstance(date, str) and re.fullmatch(r"[1-9]\d{3}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?", date.strip()):
        out["date"] = date.strip()
    return out


def tag(file_path: str, artist: str, title: str, album: str = DEFAULT_ALBUM,
        artists=None, album_artist: str | None = None, details=None) -> None:
    """Write title, artist, album and album artist.

    `artist` stays the text shown for the song, with every collaborator. When the
    source gave the performers as a list they are also written one by one (ARTISTS),
    so each one is a real artist of that song instead of one invented joint artist.
    Navidrome lists artists by *album artist*; see album_artist_for() for how it is chosen.
    """
    audio = MutagenFile(file_path, easy=True)
    if audio is None:
        return
    audio["artist"] = artist
    audio["title"] = title
    audio["album"] = album
    audio["albumartist"] = album_artist_for(artist, artists, album_artist)
    names = clean_artists(artists)
    if len(names) > 1:
        try:
            audio["artists"] = names
        except Exception:  # a container whose easy tags cannot hold the list keeps the text
            pass
    # Position in the album and year: without them an album plays in file order and cannot be
    # sorted by year. The date goes in ORIGINALDATE on purpose. Navidrome tells editions of an
    # album apart by DATE/RELEASEDATE, so writing those splits an album between songs with a
    # different date or none (checked on Navidrome 0.64.2: one album became three); the
    # original date gives the album its year and leaves the grouping alone.
    extra = clean_details(details)
    for key, name in (("track", "tracknumber"), ("disc", "discnumber"), ("date", "originaldate")):
        if key in extra:
            try:
                audio[name] = str(extra[key])
            except Exception:
                pass
    audio.save()


AUDIO_EXTENSIONS = {".m4a", ".mp3", ".flac", ".opus", ".ogg", ".webm", ".wav", ".aac", ".wma", ".aiff"}


def read_title_artist(file_path: str) -> tuple[str, str] | None:
    """(title, artist) from a file's tags, or None if unreadable."""
    try:
        audio = MutagenFile(file_path, easy=True)
    except Exception:
        return None
    if audio is None or audio.tags is None:
        return None
    title = (audio.tags.get("title") or [""])[0]
    artist = (audio.tags.get("artist") or audio.tags.get("albumartist") or [""])[0]
    return title, artist


def find_file_by_tags(
    folders: Iterable[Path],
    title: str,
    artist: str,
    norm: Callable[[str], str],
    read_tags: Callable[[str], tuple[str, str] | None] = read_title_artist,
    max_depth: int = 2,
) -> Path | None:
    """Find the audio file in `folders` (and up to `max_depth` levels below) whose
    tags match `title` (and `artist`, when the file has one). Used when a track's
    file doesn't follow Armonia's "Artist - Title" naming, e.g. music added by hand."""
    want_title, want_artist = norm(title), norm(artist)
    if not want_title:
        return None
    for folder in folders:
        if not folder.is_dir():
            continue
        base_depth = len(folder.parts)
        for path in sorted(folder.rglob("*")):
            if len(path.parts) - base_depth > max_depth or path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            tags = read_tags(str(path))
            if not tags:
                continue
            t, a = tags
            if norm(t) == want_title and (not a or not want_artist or norm(a) == want_artist):
                return path
    return None
