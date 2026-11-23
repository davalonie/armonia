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
# Prepara el ZIP en la cache compartida con build_android.py antes de entrar en Bubblewrap.
"$python" - "$root" "${GRADLE_USER_HOME:-$root/runtime/android/gradle-cache}" <<'PYGRADLE'
import fcntl
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

root, cache = map(Path, sys.argv[1:])
props = {}
for line in (root / "android/gradle/wrapper/gradle-wrapper.properties").read_text().splitlines():
    if line.strip() and not line.lstrip().startswith(("#", "!")):
        key, value = line.split("=", 1)
        props[key.strip()] = value.strip().replace(r"\:", ":")
url = props["distributionUrl"]
checksum = props["distributionSha256Sum"].lower()
if not re.fullmatch(r"[0-9a-f]{64}", checksum):
    sys.exit("distributionSha256Sum debe contener una suma SHA-256.")
if props["zipStoreBase"] != "GRADLE_USER_HOME":
    sys.exit("El proyecto debe usar GRADLE_USER_HOME para la distribucion de Gradle.")

# PathAssembler del wrapper identifica cada URL mediante su MD5 expresado en base 36.
number = int.from_bytes(hashlib.md5(url.encode(), usedforsecurity=False).digest(), "big")
digits = "0123456789abcdefghijklmnopqrstuvwxyz"
identifier = ""
while number:
    number, digit = divmod(number, 36)
    identifier = digits[digit] + identifier
name = Path(urlsplit(url).path).name
folder = cache / props["zipStorePath"] / Path(name).stem / (identifier or "0")
folder.mkdir(parents=True, exist_ok=True)
archive = folder / name

def matches(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest() == checksum

# El wrapper utiliza el mismo bloqueo de fichero al consumir o descomprimir el ZIP.
with (folder / (name + ".lck")).open("a+b") as lock:
    fcntl.lockf(lock, fcntl.LOCK_EX)
    if archive.exists():
        if matches(archive):
            sys.exit(0)
        archive.unlink()
        sys.exit("La suma del ZIP de Gradle en cache es incorrecta. Se ha retirado el archivo.")
    with tempfile.NamedTemporaryFile(dir=folder, suffix=".part", delete=False) as out:
        temporary = Path(out.name)
    try:
        subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location", "--retry", "3",
                        "--proto", "=https", "--proto-redir", "=https", "--output", str(temporary), url], check=True)
        if not matches(temporary):
            sys.exit("La suma SHA-256 de la descarga de Gradle es incorrecta.")
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
PYGRADLE

mkdir -p "$sdk/cmdline-tools" "$root/runtime"
staging=$(mktemp -d "$sdk/.preparar-XXXXXXXX")
trap 'rm -rf -- "$staging"' EXIT

# Google publica las revisiones antiguas de las herramientas en archivos individuales.
package() {
    local archive=$1 sum=$2 member=$3 destination=$4
    if [[ -e "$destination" ]]; then
        echo "Ya existe $destination con otra revision. Elige un ANDROID_HOME distinto." >&2
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
