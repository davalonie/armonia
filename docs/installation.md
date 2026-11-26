# Installation

These steps install the full stack on Linux with Docker Engine and Compose. Run them from the root of this
repository. The [main Compose file](../docker-compose.yml) starts Armonia with its web app, Navidrome, Aurral and
two private Koito instances. Only Armonia is published, on `127.0.0.1:8000` by default.

## 1. Prepare directories and credentials

Use the Linux account that will own the data. If its UID or GID is not 1000, set `MUSIC_UID` and `MUSIC_GID` in
`.env` to the values of `id -u` and `id -g`. The preparer creates the secrets that are missing and keeps the
existing ones.

```sh
cp -n .env.example .env
python3 scripts/prepare.py
```

## 2. Optional: artist metadata from Last.fm

Aurral can look up similar artists in Last.fm. To enable it, register an application at
[Last.fm](https://www.last.fm/api/account/create), save its **API key** in `secrets/lastfm-api.key` and enable the
[metadata Compose file](../compose.metadata.yaml). This command asks for the key without showing it:

```sh
python3 -c 'from getpass import getpass; from pathlib import Path; Path("secrets/lastfm-api.key").write_text(getpass("Last.fm API key: ").strip()+"\n")'
```

Add `COMPOSE_FILE=docker-compose.yml:compose.metadata.yaml` to `.env` so later starts keep it. Aurral's metadata
traffic then goes through a gateway in Armonia that only allows the metadata domains (see
[architecture.md](architecture.md#networks)). You can skip this step and start with library and history only.

For three accounts, also add `COMPOSE_PROFILES=third-user` to `.env` before starting.

## 3. Build and start

```sh
docker compose config --quiet
docker compose up --build -d --wait
```

To use a published image instead of building, set `MUSIC_IMAGE=ghcr.io/davalonie/armonia:<version>` in `.env`
and run `docker compose up -d --wait`.

## 4. Create and link the accounts

From the Linux host, use Python 3.12 with `httpx`. If you already prepared the development environment, the last
command is enough. Replace `alice bob` with one or two names of your choice (three with the profile above). Keep
the order if you run it again.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -c middleware/requirements.lock httpx
.venv/bin/python scripts/bootstrap.py --project armonia-stack --users alice bob
```

The generated passwords are stored in the private file `secrets/bootstrap-users.json`. Open
`http://localhost:8000` and sign in. The first sign-in links the Aurral account that the bootstrap assigned. If you
use other credentials or unlinked the account, connect it from **Ajustes → Recomendaciones**.

## 5. Reach it from your phone and other devices

The Android app only talks to an HTTPS origin. Put an HTTPS reverse proxy (or `tailscale serve`) in front of
`127.0.0.1:8000` and set `MUSIC_PUBLIC_ORIGIN` in `.env` to that origin, for example
`https://music.example`. Keep `MUSIC_COOKIE_SECURE=true`.

## Options in `.env`

| Variable | Default | Meaning |
| --- | --- | --- |
| `MUSIC_BIND`, `MUSIC_PORT` | `127.0.0.1`, `8000` | Where Armonia listens on the host |
| `MUSIC_UID`, `MUSIC_GID` | `1000` | Owner of the files the containers write |
| `MUSIC_IMAGE` | `armonia:local` | Image of the `music` service |
| `MUSIC_APP_NAME` | `Armonia` | Name shown in the web app (applied when the image is built) |
| `MUSIC_PUBLIC_ORIGIN` | empty | The HTTPS origin users open |
| `MUSIC_YOUTUBE_CAPABILITIES` | empty (YouTube off) | Any of `stream,offline,persist`; see [library.md](library.md#youtube-permissions) |

Two server settings are not read from `.env`; set them for the `music` service in a local Compose file of your
own (for example `compose.local.yaml`, added to `COMPOSE_FILE`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `MUSIC_DELETE_USERS` | empty | Comma-separated accounts allowed to delete files; see [access.md](access.md) |
| `MUSIC_GENERATED_PLAYLIST_SIZE` | `30` | Songs per generated list (10–50); see [recommendations.md](recommendations.md) |

Persistent data lives in `runtime/`. Back it up together with `secrets/` and your `.env`.

## Older installs and an external Navidrome

The [minimal Compose file](../compose.minimo.yaml) keeps the earlier layout (Armonia alone, or with its own
Navidrome). If you already have data with it, keep using it in the same directory and with the same project
name. To try the full stack side by side, use another clone and another `MUSIC_PORT`, so data and secrets stay
apart. If Docker says `all predefined address pools have been fully subnetted`, give the test project free
subnets through an extra local Compose file.

- With the Navidrome of the old `full` profile: `docker compose -f compose.minimo.yaml --profile full up --build -d`.
  Navidrome listens on `localhost:4533` and Armonia on `localhost:8000`.
- With an external Navidrome: set `NAVIDROME_URL` and the shared folder `MUSIC_DIR` in `.env` and run
  `docker compose -f compose.minimo.yaml up --build -d`.

## Updating

Pull the new version (or set the new `MUSIC_IMAGE` tag) and run `docker compose up --build -d --wait`. For a
running install, `tools/release/deploy.py` updates only the `music` service with an encrypted backup first; see
[tools.md](tools.md#release).
