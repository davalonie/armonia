# Playback and cache

## How a song reaches the player

A library song is streamed by Armonia from the file in `/music` (`GET /api/stream/{id}`). Armonia sends the start of
the song at once and the rest at a steady pace, faster than it plays, so a slow or mobile network is not flooded
with data the listener may skip. Offline downloads are sent whole, without pacing.

A YouTube song is played without saving it: yt-dlp resolves the audio URL, and Armonia relays it in ranged
chunks (YouTube throttles single un-ranged requests to about real time) with byte-range support, so the player can
seek.

## Variants of a song

The Android app can ask for one of three files of the same song. Each one has its own cache key on the phone,
and the server never answers one variant with another.

| Variant | What it is | When the app asks for it |
| --- | --- | --- |
| `original` | The file as stored | When neither of the others applies or can be served |
| `ligera` (light) | The same MP4/M4A audio without the cover embedded in its header, rebuilt in memory; nothing on disk changes | By default. All library songs carried their cover in the header (median 456 KB), and a player cannot make a sound before it has the whole header: without it a song needs a median of 133 KB instead of 588 KB to start (measured 18-11-2026) |
| `ahorro` (data saving) | Opus 64 kbit/s in MP4, without the embedded cover, made with ffmpeg the first time it is asked for | When the listener saves data on this network, and on any bad connection whatever the choice |

**Data saving** (Settings → *Ahorro de datos*): *never*, *on mobile data* (the default) or *always*. Below
200 kbit/s measured, every song asks for the data-saving copy whatever the setting; below 2 Mbit/s the app also asks
for smaller covers. The choice is made when a song starts and kept for that song: a change of network applies from
the next one.

On mobile data the player stops loading once 30 s of the song are buffered ahead, and goes on as it plays down.

The data-saving copies are kept on the server for later requests and removed after four days without use or
when they pass 500 MB in total (`ARMONIA_LOW_MAX_DAYS`, `ARMONIA_LOW_MAX_MB`). Nothing is converted in advance.

## Server caches

| Cache | Contents | Limits |
| --- | --- | --- |
| `runtime/cache/armonia-ahorro/` | Data-saving copies | 4 days unused / 500 MB |
| `runtime/cache/` (audio cache) | Audio from administrator-authorized HTTP sources (`config/sources.json`) | 256 MB, one day (`MUSIC_CACHE_MAX_BYTES`, `MUSIC_CACHE_TTL_SECONDS`) |
| In the browser / app | Covers, sent with long-lived cache headers (versioned covers: one year) | — |

## Phone: cache, prefill and downloads

The Android app keeps three kinds of songs on the phone:

| Kind | How it gets there | How it leaves |
| --- | --- | --- |
| **Song cache** | Everything played is kept as it streams, up to the cache size set in Settings (4 GB by default) | Least recently used first, when the cache is full |
| **Wi-Fi prefill** (*Guardar con Wi-Fi lo que más escuchas*) | Every 6 hours, on Wi-Fi or another unmetered network and with battery, the app fills up to **40 %** of the cache with: the weekly list, then your favourites, then your most played songs (by play count), for up to 8 minutes per run | Like the rest of the cache |
| **Downloads** (*Descargar en el teléfono*) | A song, album or playlist you choose to keep offline | Only when you remove it; never evicted |

The app also fetches the start of the next songs in the queue ahead of time, so a skip starts at once.

Offline, the library opens with what the phone keeps: playlists show their last known order, and **Inicio → En el
teléfono** lists everything playable without connection.

## Listens

A listen counts when you played at least half of the song or 4 minutes, whichever is less; songs shorter than 30 s
never count. The app and the web keep each listen in a durable queue and Armonia delivers it to the user's Koito,
also when the phone was offline at the time. See [recommendations.md](recommendations.md).
