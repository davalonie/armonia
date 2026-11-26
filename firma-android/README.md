# firma-android

This folder holds **your** Android signing key. Git only tracks this README: the key files are excluded in
`.gitignore` and never pushed.

## What goes here

| File | Contents |
| --- | --- |
| `test-signing.jks` | The keystore with the signing key |
| `test-signing.password` | One line with the keystore password |

These names are the ones the guides use; you can use others if you adjust the variables below.

## Why here and not in `secrets/`

The full stack mounts each service's secrets one by one, and the minimal Compose mounts `secrets/` inside the server
(for the yt-dlp cookies). The signing key lives in a folder of its own, used only by the Android build.

## Create a new key (if you have none)

```sh
chmod 700 firma-android
keytool -genkeypair -v -keystore firma-android/test-signing.jks -alias armonia \
  -keyalg RSA -keysize 4096 -validity 10000
# write the chosen password on a single line, with an editor so it stays out of the shell history
chmod 600 firma-android/*
```

## Use it when building

```sh
export MUSIC_KEYSTORE_FILE="$PWD/firma-android/test-signing.jks"
export MUSIC_KEYSTORE_PASSWORD_FILE="$PWD/firma-android/test-signing.password"
export MUSIC_KEY_ALIAS=armonia            # the alias you chose when creating it
python3 tools/android/build_android.py :app:assembleRelease
```

More in [docs/android.md](../docs/android.md#signing).

## Important

- **Keep a ciphered copy off the machine.** Android only installs an update over the app if it is signed with the
  same key. If you lose it, the app has to be uninstalled, and everything it kept on the phone is lost.
- **Do not run `git clean -x`** in the repository: it deletes ignored files, and the key is one of them.
- Never share or upload it: whoever has it can publish updates your phone will accept.
