# Tools

Every script in the repository, what it is for and how to run it. Paths are relative to the root of the clone.

## Install (`scripts/`)

| Script | Purpose |
| --- | --- |
| `scripts/prepare.py` | Creates the local directories and the missing secrets of an install. Never replaces existing values |
| `scripts/bootstrap.py --project NAME --users a b [c]` | First-install provisioning against the running stack: creates the Navidrome users, links each one to its Koito and Aurral account, and stores the generated passwords in `secrets/bootstrap-users.json`. Never prints credentials |
| `scripts/aurral-start.sh` | Aurral's entrypoint in the Compose stack: reads its secrets from files (Aurral 2.13.0 only takes them from the environment) and, with the metadata overlay, routes its metadata traffic through Armonia's gateway |

## Server maintenance (`middleware/tools/`)

Run them inside the `music` container (`docker compose exec music python -m tools.NAME …`) or from `middleware/` with
the Python environment active.

| Tool | Purpose |
| --- | --- |
| `tools.bind_oidc` | Links an Authentik identity to an existing music account ([authentik.md](authentik.md#linking-an-existing-music-account)) |
| `tools.review_recording_album` | Proposes, and then applies exactly, an album edition for a saved song ([library.md](library.md#reviewing-a-saved-songs-album)) |
| `tools.repair_album_artists` | Repairs albums split by collaborators in files imported before that fix; simulate, apply with a backup, restore |

## Development environment

| Tool | Purpose |
| --- | --- |
| `tools/preparar-entorno.sh` | Prepares a workstation: Android SDK, Gradle distribution (checksum verified), Python and web dependencies, lab tracks ([development.md](development.md)) |
| `tools/lock_python.py` | Run in the reviewed development venv to record the resolved production dependency graph in `middleware/requirements.lock` |

## Android build (`tools/android/`)

| Tool | Purpose |
| --- | --- |
| `tools/android/build_android.py [GRADLE_TASKS…]` | Builds the web, then runs Gradle inside Bubblewrap with the signing key mounted read-only. Default tasks: `:app:testDebugUnitTest :app:assembleRelease`. Outputs go to new folders under `runtime/android/` ([android.md](android.md#building)) |
| `tools/android/proxy.py` | Used by the build: the only network inside the sandbox, an HTTPS CONNECT proxy limited to the Google, Maven and Gradle repositories |

## Lab (`tools/lab/`)

| Tool | Purpose |
| --- | --- |
| `tools/lab/lab.py up\|seed\|server\|down` | The isolated lab: its own Navidrome, fictitious library and user `ana`, and the real Armonia on `127.0.0.1:18480` ([development.md](development.md#the-lab)) |
| `tools/lab/server_app.py` | The Armonia app the lab runs, with Spotify and YouTube replaced by fictitious answers |
| `tools/lab/canciones_datos.py` | Fictitious songs the size of real ones (AAC 128 kbit/s, 3:20–4:30, large embedded cover) to measure data use and start times |
| `tools/lab/nueva_importacion.py` | A new song tagged the way an import leaves it |
| `tools/lab/camino_lento.py` | A slow, delayed link between the emulator and the lab server (speed and delay read live from `camino-lento.json`) |

### Studies (`tools/lab/studies/`)

One-off measurements kept so their results can be reproduced. Each one documents its question and method at the
top of the file; they only use the lab and fictitious data.

| Study | Question |
| --- | --- |
| `comprobar_ahorro.py` | Cover cache headers and the data-saving copy (Opus 64): first request, later ones and ranges |
| `comprobar_baja.py` | The retired 96 kbit/s low-quality copy: content, ranges and timings |
| `comprobar_detalles.py` | Track number, disc and original date on some songs of an album must not split it in Navidrome |
| `comprobar_ligera.py` | The light copy (no embedded cover): identical audio and time to start over fast and slow paths |
| `comprobar_reparacion.py` | What Navidrome 0.64.2 keeps when a file's album artist changes |
| `comprobar_ritmo.py` | Pacing: the start of a song at once and the rest at a steady rate; downloads whole |
| `medir_carga.py` | Time to the first bytes directly from Navidrome versus through Armonia |
| `simular_cola.py` | A slow shared link with a queue and a song skip, as on a poor mobile connection |

## Web driver (`tools/web/`)

| Tool | Purpose |
| --- | --- |
| `tools/web/web.py SCRIPT` | Drives the lab web app with Playwright; the script gets `page(width)`, `shot(page, name)` and `LAB`. Only for the lab |
| `tools/web/recorrido.py` | A short walk through the lab web (sign in, Inicio, Biblioteca) with screenshots |

## Release

| Tool | Purpose |
| --- | --- |
| `tools/release/smoke.py IMAGE` | Starts a built image in a throwaway container without network and checks health, the web app, SQLite and FFmpeg |
| `tools/release/deploy.py` | Updates only the `music` service of a running stack |

`deploy.py` takes the stack directory (`--stack`), every active Compose file in order (`-f`), the new local image tag
(`--image`), the sha256 ID of the image in use (`--expected`) and the exact commit of the new image (`--commit`). The
new image must carry the OCI label `org.opencontainers.image.revision` with that commit, and the stack must select
its image through `MUSIC_IMAGE`. It checks that no download or import is running, stops only `music`, writes an
encrypted backup of its data and configuration to `backups/`, switches the image and checks the result; if that
fails it starts the previous image again. Keep the backup key outside the machine to be able to restore it.

Build the image from a clean checkout of the commit you deploy:

```sh
REVISION=$(git rev-parse HEAD)
docker build --build-arg ARMONIA_COMMIT=$REVISION --build-arg ARMONIA_VERSION=0.8.0 \
  -t armonia:local-${REVISION:0:12} middleware
python tools/release/smoke.py armonia:local-${REVISION:0:12}
```

Published images are on the GitHub Container Registry as `ghcr.io/davalonie/armonia:<version>`, and signed APKs are
attached to the [GitHub releases](https://github.com/davalonie/armonia/releases).
