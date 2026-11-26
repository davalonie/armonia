# Development

## Repository layout

| Path | Contents |
| --- | --- |
| `middleware/` | The server (FastAPI, Python 3.12): `main.py`, `routes/`, `services/`, `homelab/` (integrations), `tests/`, and the `Dockerfile` of the image |
| `middleware/frontend/` | The Svelte web app, also bundled into the Android app (`--mode capacitor`) |
| `android/` | The Android app: Capacitor bridge and Kotlin core (one Gradle project, module `app`) |
| `scripts/` | Install-time scripts used by the Compose stack |
| `tools/` | Development, lab, build and release tools ([tools.md](tools.md)) |
| `config/` | Example of administrator-authorized sources |
| `docs/` | This documentation |
| `firma-android/` | Your Android signing key (git only tracks its README) |
| `runtime/` | Everything generated locally: SDK, caches, lab data, build outputs (ignored by git) |

## Prepare a Linux x86-64 workstation

Install Python 3.12 with `venv`, Node 24 with npm, JDK 25, Docker with Compose, Bubblewrap (`bwrap`), FFmpeg, curl
and unzip. Export `JAVA_HOME` pointing to the JDK. For the browser's system packages, Playwright offers
`python -m playwright install-deps chromium webkit`.

Then run, from the clone:

```sh
tools/preparar-entorno.sh
```

It downloads the Android tools into `runtime/`, installs the Python and web dependencies, builds the web and creates
44 fictitious tracks for the lab. The SDK may ask you to accept its licences. The Gradle distribution is downloaded
from the URL in `android/gradle/wrapper/gradle-wrapper.properties` and checked against its `distributionSha256Sum`
before it is placed in the Gradle cache.

| Variable | Use | Default |
| --- | --- | --- |
| `PYTHON` | Interpreter that creates the venv | `python3.12` |
| `ARMONIA_VENV` | Absolute path of the Python environment | `.venv` in the clone |
| `JAVA_HOME` | JDK for the Android build | required |
| `ANDROID_HOME` | Local SDK | `runtime/android-sdk` |
| `GRADLE_USER_HOME` | Gradle cache | `runtime/android/gradle-cache` |
| `PLAYWRIGHT_BROWSERS_PATH` | Browser cache | `runtime/browsers` |
| `ARMONIA_CHROMIUM` | Alternative Chromium for the web driver | Playwright's |
| `DOCKER_CONFIG` | Docker configuration for the lab and the release tools | `runtime/docker-config` |

Validated versions (22-11-2026): Android platform 37.0, build-tools 36.0.0, platform-tools 37.0.1, emulator 37.3.8
with an API 35 `default;x86_64` image, Gradle 9.7.1, Python 3.12.3, Node 24.20.0 with npm 11.19.0, Playwright
1.65.0.

## Tests

Activate the venv in each terminal and run from the root of the clone:

```sh
. .venv/bin/activate
(cd middleware && ruff check . && pytest -q tests)
(cd middleware/frontend && npm test && npm run build)
python3 tools/android/build_android.py :app:testDebugUnitTest :app:assembleDebug
```

## The lab

The lab is an isolated install with fictitious data: its own Navidrome 0.64.2, the real Armonia server, generated
tracks and covers, and the fictitious user `ana`. It only listens on 127.0.0.1 and never touches a real install.

```sh
python tools/lab/lab.py up       # start the lab's Navidrome
python tools/lab/lab.py seed     # library, playlists and favourites for «ana»
python tools/lab/lab.py server   # Armonia on 127.0.0.1:18480, in the foreground
```

In another terminal, `python tools/web/web.py tools/web/recorrido.py` signs in with Chromium, visits Inicio and
Biblioteca and saves screenshots in `runtime/capturas/`. Stop the server with Ctrl+C and run
`python tools/lab/lab.py down`. The lab data stays in `runtime/lab/`.

To test the Android app against the lab, run it in an emulator and forward the port with
`adb reverse tcp:18480 tcp:18480`; debug builds accept `http://127.0.0.1:18480`. `tools/lab/camino_lento.py` puts a
slow, delayed link between the emulator and the lab server, because the emulator's own network throttling does not
apply.

## Continuous integration

| Workflow | Runs on | What it does |
| --- | --- | --- |
| [Backend and web validation](../.github/workflows/middleware-ci.yml) | Pushes and pull requests that touch `middleware/` | Ruff, pytest, web tests and build |
| [Android validation](../.github/workflows/android-build.yml) | Pushes and pull requests that touch `android/` or `middleware/frontend/` | Debug APK, JVM tests and the instrumentation APK, without signing secrets |
| [Validate Docker image](../.github/workflows/docker-publish.yml) | Manual | Builds the image without pushing |

Publishing the image and the signed APK is a manual operator task; see [tools.md](tools.md#release).
