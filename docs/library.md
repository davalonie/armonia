# Library: when a song is saved into Navidrome

Navidrome only knows the files in its library folders. Armonia can also play songs that are not there (YouTube,
administrator-authorized HTTP sources), so it matters when a song becomes a real file in your library and when it
does not.

## A song is saved into your library when

| Action | What happens |
| --- | --- |
| **Importing a Spotify playlist** (link, Exportify CSV or ZIP) | Each song is first looked up in your library. Songs that are not there are searched on YouTube; when there are several plausible recordings the song waits in a review list for you to pick one. The chosen recording is downloaded (M4A) into your library folder, Navidrome rescans, and a Navidrome playlist is created with the songs found, in the original order |
| **Saving a YouTube song into a playlist or your favourites** (*Guardar en una playlist* → *Descargar y guardar*) | A normal playlist can only hold library songs, so the recording is downloaded into your library first and then added |
| **Providing an MP3** (*Pendientes de añadir*) | Songs an import could not find wait in this list. For each one you can pick an MP3 you have the right to keep; it is stored in your library as MP3 192 kbit/s, and the original on your device is kept |
| **An administrator-authorized HTTP source** with the `persist` permission (`config/sources.json`) | Saved like a YouTube recording |

Every saved file is tagged with title, artists and album. With the metadata Compose file, when a YouTube Music
track only names itself as its album (or has none), Armonia asks Apple's public catalogue and uses an album edition
only when title, full credits and duration match a single candidate. The file is written to a temporary folder,
checked again and moved into the folder Navidrome assigns to your account. Armonia records each saved source, so
the same recording is not saved twice.

## A song is *not* saved when

- **You play it.** Listening to a YouTube song, however many times, never writes it into the library. There is no
  rule that saves a song after a number of listens.
- **It is in a mixed playlist** (*lista mixta*). Mixed playlists live in Armonia's own database and can hold library
  songs and external references side by side; the external ones stay external.
- **It is in a generated playlist** (the weekly list, the artist mixes). They are references resolved to your library
  first and to an authorized external source otherwise; nothing is downloaded. *Guardar una copia en tu biblioteca*
  makes an independent mixed playlist, still without downloading.
- **The phone keeps it.** The song cache, the Wi-Fi prefill and *Descargar en el teléfono* keep copies on the phone
  only; see [playback-and-cache.md](playback-and-cache.md).

## YouTube permissions

YouTube is off until the administrator sets `MUSIC_YOUTUBE_CAPABILITIES` in `.env` to one or more of:

| Permission | Allows |
| --- | --- |
| `stream` | Playing YouTube songs without saving them |
| `offline` | Offline copies of YouTube songs on the phone |
| `persist` | Saving YouTube recordings into the library (imports, *Descargar y guardar*) |

Download only content whose download the service allows and for which you hold the rights or permission.

## Reviewing a saved song's album

Inside the `music` container (or from `middleware/` with the Python environment active):

```sh
python -m tools.review_recording_album "/music/path/song.m4a" > plan.json
python -m tools.review_recording_album "/music/path/song.m4a" --aplicar plan.json --copia "/backup/song.m4a"
```

The first command proposes an album edition with its evidence link; check it before applying. The second applies
exactly that proposal and keeps the whole original file at `--copia`. Rescan the library in Navidrome afterwards.
For albums split by collaborators in files imported before that fix, `python -m tools.repair_album_artists ROOT`
simulates the repair, `--aplicar --copia backup.json` writes it and `--restaurar backup.json` undoes it.

## Deleting

Deleting a file from the library needs a Navidrome administrator and an entry in `MUSIC_DELETE_USERS`; see
[access.md](access.md).
