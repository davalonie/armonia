# Android app

## How it is built

The app is the same Svelte interface as the web (`middleware/frontend`), built in `capacitor` mode and bundled
into the APK, inside a [Capacitor](https://capacitorjs.com/) WebView. Under it, a Kotlin core does what a web page
cannot do well:

| Part | Where | What it does |
| --- | --- | --- |
| Interface | `middleware/frontend/src` (shared with the web; phone-only bits behind `mobile` / `.capacitor`) | Every screen, including sign-in |
| Bridge | `android/app/src/main/java/com/armonia/app/web/` | The activities (`LaunchActivity`, `LoginActivity`, `LibraryActivity`) and the Capacitor plugins the page calls (`Armonia`, `ArmoniaLogin`, `ArmoniaImport`) |
| Playback | `…/playback/` | Media3 player and `MediaLibraryService`: queue, shuffle, notification and lock-screen controls, data saving, listens |
| Offline | `…/offline/` | Song cache, Wi-Fi prefill, downloads (Media3 `DownloadService`) |
| Session and data | `…/security/`, `…/data/`, `…/homelab/` | Sign-in, session in Android Keystore, server API clients |
| Android Auto | `…/auto/`, `PlaybackService` | Browse and play from the car through the media library service |

The page opens from the bundled files, also on a cold start without connection. Screens talk to the server through
the native HTTP client with the account's session. The queue, position, audio, downloads, listens and Android Auto
belong to the Kotlin player, so music keeps playing with the interface closed.

Until version 0.7.0 there was also a separate Android interface written in Jetpack Compose. It was removed in
0.8.0; the tags `recuperar-interfaz-compose` and `ultima-app-kotlin` keep it in the history. The phone screens were
ported from it, and comments in the web code that cite files such as `ui/player/QueueSheet.kt` refer to that
interface: `git show ultima-app-kotlin:android/app/src/compose/java/com/armonia/app/ui/player/QueueSheet.kt`.

## Requirements

JDK 25, the Android SDK (platform 37, build-tools 36.0.0), Node 24 with npm, and Bubblewrap (`bwrap`) for the
sandboxed build. `tools/preparar-entorno.sh` installs the SDK and the web dependencies into `runtime/`; see
[development.md](development.md).

## Signing

Android only installs an update over the app if it is signed with the same key. Keep the keystore and its password
file in [`firma-android/`](../firma-android/README.md) (git only tracks its README) and a ciphered copy off the
machine. Export:

```sh
export MUSIC_KEYSTORE_FILE="$PWD/firma-android/test-signing.jks"
export MUSIC_KEYSTORE_PASSWORD_FILE="$PWD/firma-android/test-signing.password"
export MUSIC_KEY_ALIAS=armonia
```

If the key entry has its own password, set `MUSIC_KEY_PASSWORD`. Release builds refuse to run without a key.

## Building

```sh
python3 tools/android/build_android.py :app:assembleRelease :app:testDebugUnitTest
```

The script builds the web first (with the system's Node), then runs the project's Gradle wrapper inside
Bubblewrap with no network except a proxy limited to the dependency repositories, and the key mounted read-only.
The APK and test reports are copied to new folders under `runtime/android/` (it prints their paths).

On a machine with little memory (7 GiB), add:

```sh
  --max-workers=1 -x :app:lintVitalAnalyzeRelease -Pkotlin.compiler.execution.strategy=in-process \
  '-Dorg.gradle.jvmargs=-Xmx1280m -XX:MaxMetaspaceSize=512m -XX:ActiveProcessorCount=2 -Dfile.encoding=UTF-8'
```

To run Gradle directly (Android Studio, CI): `cd android && ./gradlew :app:assembleDebug`. Gradle then builds the web
itself with `npm run build -- --mode capacitor` (run `npm ci` in `middleware/frontend` first). With
`-PmusicPrebuiltWeb=<dir>` it takes an already built web from `<dir>/public` instead.

| Gradle property | Default | Meaning |
| --- | --- | --- |
| `musicApplicationId` | `io.github.davalonie.armonia` | Application ID (debug adds `.debug`) |
| `musicAppName` | `Armonia` | Name under the icon |
| `musicVersionCode` | `10080` (0.8.0) | Version code |
| `musicPrebuiltWeb` | — | Folder with an already built web |

## Installing and updating

```sh
adb install -r path/to/app-release.apk
```

`-r` updates in place and keeps the session, the cache and the downloads. Never uninstall to update: it deletes
everything the app keeps on the phone. 0.8.0 installs as an update of the 0.7.0 app (same ID and key, higher
version code); in the lab emulator the update kept the session and the last queue.

On first start, enter the HTTPS address of your server (`MUSIC_PUBLIC_ORIGIN`). Release builds only accept HTTPS;
debug builds also accept HTTP, for the lab.

## Android Auto

The car browses the library through the same `MediaLibraryService` and plays with the same player, with the phone's
interface closed. To see a sideloaded build in the car, enable **Unknown sources** in Android Auto's developer
settings. [Testing media apps in Android Auto](https://developer.android.com/training/cars/testing#unknown-sources)

The instrumentation test `CarLibraryTest` checks the catalogue through Android's classic media browser and playback
through Media3. It needs a signed-in debug app and the name of a playlist:

```sh
cd android && ./gradlew :app:assembleDebug :app:assembleDebugAndroidTest
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb shell am instrument -w -e playlist "Playlist name" \
  io.github.davalonie.armonia.debug.test/androidx.test.runner.AndroidJUnitRunner
```

Without `-e playlist` both tests are skipped.

## Measured footprint

Measured on 26-11-2026 in the lab emulator (Android 15, software GPU), release builds of 0.7.0 (Compose) and of the
WebView interface, same account:

| | Compose (0.7.0) | WebView interface |
| --- | --- | --- |
| Memory at rest (PSS) | 79 MB | 163 MB (96 app + 67 WebView) |
| Memory while playing | 89 MB | 175 MB |
| CPU while playing, screen off | 3.4 % | 2.9 % |
| CPU while playing, Home on screen | 4.9 % | 8.7 % |
| Cold start to first frame (median) | 1024 ms | 1163 ms |

The WebView costs about 85–100 MB more memory. Background playback, where most listening happens, costs the same
because it runs in the shared Kotlin core.
