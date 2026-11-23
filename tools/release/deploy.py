"""Actualiza unicamente el servicio music de un stack ya instalado."""
import argparse
import base64
import fcntl
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tarfile
import tempfile
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[2]
MAGIC = b"ARMONIA-APP-BACKUP-v1\n"


def capture(args, cwd, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"La operacion de Docker fallo con codigo {result.returncode}.")
    return result.stdout.strip()


def check_idle(stack):
    with sqlite3.connect((stack / "runtime/music-app/armonia.db").as_uri() + "?mode=ro", uri=True) as db:
        downloads = db.execute("SELECT 1 FROM downloads WHERE status IN "
                               "('pending','queued','downloading','running','processing','tagging','scanning') LIMIT 1").fetchone()
        imports = db.execute("SELECT 1 FROM playlist_imports WHERE json_extract(payload,'$.status')='running' LIMIT 1").fetchone()
        if downloads or imports:
            raise RuntimeError("Hay una descarga o importacion activa.")


def replace_env(path, contents):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        try:
            tmp.write(contents)
            tmp.flush()
            os.fsync(tmp.fileno())
            os.replace(tmp.name, path)
        finally:
            Path(tmp.name).unlink(missing_ok=True)


def archive_before_upgrade(stack, files):
    key = base64.urlsafe_b64decode((stack / "secrets/backup.key").read_bytes().strip())
    cipher = AESGCM(key)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in files:
            if path.exists():
                tar.add(path, arcname=path.relative_to(stack))
    nonce = os.urandom(12)
    folder = stack / "backups"
    folder.mkdir(mode=0o700, exist_ok=True)
    path = folder / f"armonia-previa-{time.time_ns()}.agcm"
    with path.open("xb") as out:
        out.write(MAGIC + nonce + cipher.encrypt(nonce, buf.getvalue(), MAGIC))
        out.flush()
        os.fsync(out.fileno())
    raw = path.read_bytes()
    if cipher.decrypt(raw[len(MAGIC):len(MAGIC)+12], raw[len(MAGIC)+12:], MAGIC) != buf.getvalue():
        raise RuntimeError("La copia de recuperacion no coincide.")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", required=True, type=Path)
    parser.add_argument("--image", required=True, help="Etiqueta local nueva")
    parser.add_argument("--expected", required=True, help="ID sha256 de la imagen actualmente en uso")
    parser.add_argument("--commit", required=True, help="Commit exacto de la imagen nueva")
    parser.add_argument("-f", "--file", action="append", required=True, help="Archivo Compose activo, en orden")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/@-]*", args.image):
        parser.error("Etiqueta de imagen invalida")
    os.umask(0o077)
    stack = args.stack.resolve(strict=True)
    files = [(stack / name).resolve(strict=True) for name in args.file]
    if any(not p.is_relative_to(stack) for p in files):
        parser.error("Los archivos Compose deben pertenecer al stack")
    env = os.environ.copy()
    env.pop("MUSIC_IMAGE", None)
    docker = ["docker", "--config", env.get("DOCKER_CONFIG", str(ROOT / "runtime/docker-config"))]
    compose = [*docker, "compose"]
    for path in files:
        compose.extend(["-f", str(path)])

    def run(args, environment=env):
        return capture(args, stack, environment)

    def container():
        cid = run([*compose, "ps", "-q", "music"])
        return json.loads(run([*docker, "inspect", cid]))[0]

    def healthy(state):
        return state["State"].get("Health", {}).get("Status") == "healthy"

    env_file = stack / ".env"
    with (stack / ".deploy.lock").open("a") as deploy_lock, (stack / ".backup.lock").open("a") as backup_lock:
        for lock in (deploy_lock, backup_lock):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old = container()
        labels = old["Config"]["Labels"]
        if (Path(labels["com.docker.compose.project.working_dir"]).resolve() != stack
                or old["Image"] != args.expected or not healthy(old)):
            raise RuntimeError("El servicio activo, su imagen o su salud difiere de lo esperado.")
        target = json.loads(run([*docker, "image", "inspect", args.image]))[0]
        if target["Config"].get("Labels", {}).get("org.opencontainers.image.revision") != args.commit:
            raise RuntimeError("El commit de la imagen difiere del solicitado.")
        for image_env, expected in ((env, old["Config"]["Image"]), ({**env, "MUSIC_IMAGE": args.image}, args.image)):
            cfg = json.loads(run([*compose, "config", "--format", "json"], image_env))
            if cfg["services"]["music"]["image"] != expected:
                raise RuntimeError("La configuracion Compose de music debe seleccionar la imagen con MUSIC_IMAGE.")
        check_idle(stack)
        previous = env_file.read_bytes() if env_file.exists() else None
        old_text = previous or b""
        pattern = rb"(?m)^(?:export\s+)?MUSIC_IMAGE\s*=.*$"
        if len(re.findall(pattern, old_text)) > 1:
            raise RuntimeError("MUSIC_IMAGE tiene mas de una definicion.")
        line = b"MUSIC_IMAGE=" + args.image.encode("ascii")
        updated = re.sub(pattern, line, old_text) if re.search(pattern, old_text) else old_text.rstrip(b"\n") + b"\n" + line + b"\n"
        restart = [*compose, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "90", "music"]
        mounted = [Path(m["Source"]).resolve() for m in old["Mounts"] if m["Destination"].startswith("/run/secrets/")]
        if any(not path.is_relative_to(stack) for path in mounted):
            raise RuntimeError("Revisa la ubicacion de los secretos montados.")
        run([*compose, "stop", "music"])
        changed = False
        try:
            check_idle(stack)
            backup = archive_before_upgrade(stack, [stack / "runtime/music-app", *files, env_file, stack / "config", *mounted])
            if (env_file.read_bytes() if env_file.exists() else None) != previous:
                raise RuntimeError("El archivo .env cambio durante la actualizacion.")
            replace_env(env_file, updated)
            changed = True
            run(restart)
            current = container()
            if current["Image"] != target["Id"] or not healthy(current):
                raise RuntimeError("El servicio actualizado no alcanzo el estado esperado.")
        except BaseException:
            if changed:
                if previous is None:
                    env_file.unlink()
                else:
                    replace_env(env_file, previous)
            run(restart)
            if container()["Image"] != args.expected:
                raise RuntimeError("La reversion requiere revision manual.")
            raise
        print("Servicio music actualizado. Copia de recuperacion:", backup.name)


if __name__ == "__main__":
    main()
