"""Compila Android en Linux con Bubblewrap y el wrapper de Gradle del proyecto."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "runtime/android"
PROXY = Path(__file__).with_name("proxy.py")
TASKS = [":app:testDebugUnitTest", ":app:assembleRelease"]


def main():
    sdk = Path(os.environ.get("ANDROID_HOME", ROOT / "runtime/android-sdk")).resolve()
    cache = Path(os.environ.get("GRADLE_USER_HOME", OUTPUT / "gradle-cache")).resolve()
    java = Path(os.environ["JAVA_HOME"]).resolve()
    if not (sdk / "build-tools/36.0.0").is_dir() or not (java / "bin/java").is_file():
        sys.exit("Revisa ANDROID_HOME y JAVA_HOME en docs/ENTORNO.md.")
    cache.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    env = {"HOME": "/work/home", "PATH": "/jdk/bin:/usr/bin:/bin", "JAVA_HOME": "/jdk",
           "ANDROID_HOME": "/sdk", "GRADLE_USER_HOME": "/gradle-cache", "LANG": "C.UTF-8",
           "AUDIT_PROXY_SOCK": "/work/proxy.sock"}
    # El proxy solo admite los dominios HTTPS de las dependencias de compilacion.
    env["JAVA_TOOL_OPTIONS"] = "-Dhttps.proxyHost=127.0.0.1 -Dhttps.proxyPort=18888"
    with tempfile.TemporaryDirectory(prefix="build-", dir=OUTPUT) as tmp:
        work = Path(tmp)
        project = work / "project"
        shutil.copytree(ROOT / "android", project, ignore=shutil.ignore_patterns(
            ".gradle", ".kotlin", "build", "local.properties", "keystore.properties",
            "*.jks", "*.keystore", "*.password", "*.apk"))
        (work / "home").mkdir()
        args = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session"]
        for path in ("/usr", "/bin", "/lib", "/lib64", "/etc/ssl", "/etc/alternatives"):
            if Path(path).exists():
                args.extend(["--ro-bind", path, path])
        args.extend(["--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
                     "--ro-bind", str(java), "/jdk", "--ro-bind", str(sdk), "/sdk",
                     "--bind", str(cache), "/gradle-cache", "--bind", tmp, "/work",
                     "--ro-bind", str(PROXY), "/work/proxy.py", "--chdir", "/work/project"])
        if "MUSIC_KEYSTORE_FILE" in os.environ:
            key = Path(os.environ["MUSIC_KEYSTORE_FILE"]).resolve(strict=True)
            args.extend(["--ro-bind", str(key), "/signing.jks"])
            env["MUSIC_KEYSTORE_FILE"] = "/signing.jks"
            for name in ("MUSIC_KEY_ALIAS", "MUSIC_KEYSTORE_PASSWORD", "MUSIC_KEY_PASSWORD"):
                if name in os.environ:
                    env[name] = os.environ[name]
            if "MUSIC_KEYSTORE_PASSWORD_FILE" in os.environ:
                env["MUSIC_KEYSTORE_PASSWORD"] = Path(os.environ["MUSIC_KEYSTORE_PASSWORD_FILE"]).read_text().rstrip("\r\n")
        bridge = ('/usr/bin/python3 /work/proxy.py bridge >/dev/null 2>&1 & '
                  'exec ./gradlew --no-daemon -Dorg.gradle.workers.max=1 --console=plain "$@"')
        args.extend(["/bin/sh", "-c", bridge, "gradle", *(sys.argv[1:] or TASKS)])
        proxy = subprocess.Popen([sys.executable, str(PROXY), "host", str(work / "proxy.sock")],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                if (work / "proxy.sock").is_socket():
                    break
                if proxy.poll() is not None:
                    sys.exit("El proxy de compilacion termino antes de arrancar.")
                time.sleep(0.1)
            subprocess.run(args, env=env, check=True)
            for name in ("outputs", "test-results"):
                source = project / "app/build" / name
                if source.exists():
                    # Solo se exportan los archivos de esta ejecucion.
                    destination = Path(tempfile.mkdtemp(prefix=name + "-", dir=OUTPUT))
                    shutil.copytree(source, destination, dirs_exist_ok=True)
                    print(destination.relative_to(ROOT))
        finally:
            proxy.terminate()
            proxy.wait()


if __name__ == "__main__":
    main()
