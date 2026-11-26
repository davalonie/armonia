# Architecture

Armonia is one container (`music`) in front of upstream services that it does not modify. Everything below
refers to the main [docker-compose.yml](../docker-compose.yml).

## Services

| Service | Image | Role |
| --- | --- | --- |
| `music` | built from [`middleware/`](../middleware) | Armonia: FastAPI server, the Svelte web app, imports, streaming, the adapters to the other services |
| `navidrome` | `deluan/navidrome:0.64.2` | Accounts, music libraries, playlists, favourites, scans (Subsonic API) |
| `koito-alice`, `koito-bob` (`koito-carol` with the `third-user` profile) | `gabehf/koito:v0.3.2` | Listening history, one private instance per user |
| `aurral` | `ghcr.io/lklynet/aurral:2.13.0` | Recommendations: weekly flow and similar artists |

Only `music` publishes a port (`MUSIC_BIND:MUSIC_PORT`, `127.0.0.1:8000` by default). Put an HTTPS reverse proxy
(or `tailscale serve`) in front of it to reach it from other devices.

## Networks

Each upstream service lives on its own internal Docker network, and only `music` joins all of them:

| Network | Members | Internal |
| --- | --- | --- |
| `entry` | `music` | no (the published port) |
| `library` | `music`, `navidrome` | yes |
| `recommendations` | `music`, `aurral` | yes |
| `history_alice`, `history_bob`, `history_carol` | `music` and that user's Koito | yes |

Internal networks have no route to the internet. Aurral still needs to reach metadata providers; with the
optional [metadata overlay](../compose.metadata.yaml) it does so through a CONNECT gateway inside `music` that only
allows `ws.audioscrobbler.com` (Last.fm), `api.deezer.com`, `musicbrainz.org` and `lidarrapi.brainzmash.cc` on
port 443. TLS stays end to end.

## Accounts

- A user signs in with their **Navidrome** user and password (or with Authentik, see
  [authentik.md](authentik.md)). Armonia keeps an encrypted per-user Subsonic credential and uses it for every
  library request, also in background jobs.
- `scripts/bootstrap.py` creates the Navidrome users and links each one to a Koito instance and an Aurral
  account (`secrets/integrations.json`).
- Each user only sees the library folders Navidrome assigns to them. See [access.md](access.md).

## Ports inside `music`

| Port | Listener | Who uses it |
| --- | --- | --- |
| 8000 | `main:app` | Browsers and the Android app: the public API, the web app and `/health` |
| 8001 | `internal_main:app` | Aurral only, never published: a read-only view of a user's top artists from Koito, behind a random per-user URL |

## Data

| Path on the host | Contents |
| --- | --- |
| `runtime/music/` | The music files (mounted in Navidrome and in `music` as `/music`) |
| `runtime/music-app/` | Armonia's SQLite database `armonia.db` (sessions, imports, listens outbox, generated playlists) |
| `runtime/cache/` | Server caches (authorized HTTP audio, data-saving copies) |
| `runtime/navidrome/`, `runtime/koito-*/`, `runtime/aurral/` | Each upstream service's own data |
| `secrets/` | Keys, tokens and generated passwords; never in git |

## The Android app

The app is the same web interface, built in `capacitor` mode and bundled into the APK, running in a Capacitor
WebView. A Kotlin core under it does what a web page cannot: Media3 playback with a notification and lock-screen
controls, the song cache and offline downloads, the session in Android Keystore, and Android Auto. See
[android.md](android.md).

## Where a request goes

| Action | Path |
| --- | --- |
| Browse the library, playlists, favourites | App → Armonia → Navidrome (Subsonic) |
| Play a library song | App → Armonia `/api/stream` → the file, with pacing and an optional lighter copy ([playback-and-cache.md](playback-and-cache.md)) |
| Play a YouTube song | App → Armonia → yt-dlp resolves the audio URL → Armonia relays it in ranged chunks |
| Count a listen | App → Armonia (durable outbox) → the user's Koito |
| Recommendations | Aurral reads top artists from port 8001 → Armonia builds playlists from Aurral's results ([recommendations.md](recommendations.md)) |
| Save a song | Armonia downloads or receives the file → writes it into the user's library folder → asks Navidrome to scan ([library.md](library.md)) |
