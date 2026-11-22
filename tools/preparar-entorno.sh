#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd -P)
sdk=${ANDROID_HOME:-"$root/runtime/android-sdk"}
python=${PYTHON:-python3.12}
venv=${ARMONIA_VENV:-"$root/.venv"}
export ANDROID_HOME="$sdk"
export PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH:-"$root/runtime/browsers"}
[[ $(node -p 'process.versions.node.split(".")[0]') == 24 ]] || { echo 'Se necesita Node 24.' >&2; exit 1; }
"$python" -c 'import sys; assert sys.version_info[:2] == (3,12), "Se necesita Python 3.12"'
mkdir -p "$sdk/cmdline-tools" "$root/runtime"
staging=$(mktemp -d "$sdk/.preparar-XXXXXXXX")
trap 'rm -rf -- "$staging"' EXIT

# Google publica las revisiones antiguas de las herramientas en archivos individuales.
package() {
    local archive=$1 sum=$2 member=$3 destination=$4
    if [[ -e "$destination" ]]; then
        echo "Ya existe $destination con otra revisión. Elige un ANDROID_HOME distinto." >&2
        return 1
    fi
    mkdir -p "$staging/$member"
    curl -fsSL --retry 3 "https://dl.google.com/android/repository/$archive" -o "$staging/package.zip"
    echo "$sum  $staging/package.zip" | sha256sum --check --status
    unzip -q "$staging/package.zip" -d "$staging/$member"
    mv -T "$staging/$member/$member" "$destination"
}

revision() {
    [[ -f "$1/source.properties" ]] && grep -Eq "^Pkg.Revision[[:space:]]*=[[:space:]]*${2//./\\.}[[:space:]]*$" "$1/source.properties"
}

cli="$sdk/cmdline-tools/15859902"
if [[ ! -x "$cli/bin/sdkmanager" ]]; then
    package commandlinetools-linux-15859902_latest.zip 4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583 cmdline-tools "$cli"
fi
if ! revision "$sdk/platform-tools" 37.0.1; then
    package platform-tools_r37.0.1-linux.zip d230f13842f60f782a8645f9c813f8f845bf36089ea7289f28c48f17979313f1 platform-tools "$sdk/platform-tools"
fi
if ! revision "$sdk/emulator" 37.3.8; then
    package emulator-linux_x64-16847572.zip 0127e7c763f8db1915095cc761cfb6504b94cc8846b618c9faf973fd04780426 emulator "$sdk/emulator"
fi
packages=()
revision "$sdk/platforms/android-37.0" 2 || packages+=("platforms;android-37.0")
revision "$sdk/build-tools/36.0.0" 36.0.0 || packages+=("build-tools;36.0.0")
revision "$sdk/system-images/android-35/default/x86_64" 2 || packages+=("system-images;android-35;default;x86_64")
if (( ${#packages[@]} )); then
    "$cli/bin/sdkmanager" --sdk_root="$sdk" "${packages[@]}"
fi
revision "$sdk/platforms/android-37.0" 2
revision "$sdk/build-tools/36.0.0" 36.0.0
revision "$sdk/system-images/android-35/default/x86_64" 2
revision "$sdk/platform-tools" 37.0.1
revision "$sdk/emulator" 37.3.8

[[ -x "$venv/bin/python" ]] || "$python" -m venv "$venv"
"$venv/bin/python" -m pip install -r "$root/middleware/requirements-dev.txt" playwright==1.65.0
(cd "$root/middleware/frontend" && npm ci --no-fund --no-audit && npm run build)
"$venv/bin/python" -m playwright install chromium --only-shell
"$venv/bin/python" -m playwright install webkit
(cd "$root/tools/lab" && "$venv/bin/python" -c 'import lab, canciones_datos, nueva_importacion; lab.fixtures(); canciones_datos.make(scan=False); nueva_importacion.make()')
