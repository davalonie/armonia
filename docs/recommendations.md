# Recommendations

Recommendations come from **Aurral**; Armonia only feeds it your top artists and turns its results into playlists
you can play. Your listening history stays in your own Koito.

## Listening history

A listen counts when you played at least half of the song or 4 minutes, whichever is less (songs shorter than 30 s
never count). The web and the app keep listens in a durable queue, and Armonia delivers them to the Koito instance
of that account, also when the phone was offline when you listened.

## Seeds

Armonia reads your most played artists from Koito and identifies them in MusicBrainz (only artist and title
queries; never users, counts or times). Up to **5** identified artists become the *seeds*. Aurral gets the
seeds' MusicBrainz IDs and names, never your history: it reads them from Armonia's internal port through a
private per-user address (see [architecture.md](architecture.md#ports-inside-music)).

## Generated playlists (Inicio → Hecho para ti)

| Playlist | Built from | Renewed |
| --- | --- | --- |
| **Armonia semanal** | Aurral's weekly flow for your account: songs by artists similar to your seeds (focus mix, all similar artists) | Aurral runs it every **Friday at 00:00** (Aurral's clock, UTC in the stack). Armonia also asks for a new run when your seeds change, and when you press *Regenerar* |
| **Mix *Artist*** (one per seed) | Artists similar to that seed according to Aurral, up to 3 songs per artist | Re-read daily, rebuilt weekly |

Each list holds 30 songs by default (`MUSIC_GENERATED_PLAYLIST_SIZE`, 10–50). Every candidate is resolved to your
library first and to an administrator-permitted external source (YouTube) otherwise; candidates with neither are
left out. **Nothing is downloaded or written to Navidrome** (see [library.md](library.md)). A refresh never touches
a queue that is already playing.

If the weekly list is empty, Inicio says whether Aurral is still building it or found nothing for your artists
this week; *Regenerar* asks Aurral for a new run and waits up to two minutes for it.

With the [metadata Compose file](../compose.metadata.yaml) and a Last.fm key, Aurral finds similar artists through
Last.fm; Armonia passes each seed's name as well as its MusicBrainz ID, because Last.fm does not know every MBID.

## Continue with similar music

When a queue ends, Armonia adds a small batch of 5 related songs and keeps playing: songs from your generated
lists that involve the artists you just heard come first, then the rest. A YouTube recording you picked can also
seed its own radio. It is on by default and can be turned off in **Ajustes**.

## Similar artists on Inicio

*Artistas similares a los que escuchas* shows the artists Aurral relates to your seeds; each one opens its artist
page.
