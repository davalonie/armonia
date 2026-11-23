"""Arranca la imagen local de Armonia sin red y verifica el arranque real."""
import argparse
import os
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[2]
CHECK = """
import json, sqlite3, subprocess, time
from pathlib import Path
from urllib.request import urlopen

for attempt in range(60):
    try:
        with urlopen('http://127.0.0.1:8000/health', timeout=2) as response:
            if json.load(response) == {'status': 'ok'}:
                break
    except OSError:
        pass
    time.sleep(1)
else:
    raise SystemExit('El servidor no esta sano.')
with urlopen('http://127.0.0.1:8000/') as response:
    html = response.read().lower()
    if b'/assets/' not in html:
        raise SystemExit('La web compilada no se sirve.')
with sqlite3.connect('file:/app/data/armonia.db?mode=ro', uri=True) as db:
    if db.execute('pragma quick_check').fetchone()[0] != 'ok':
        raise SystemExit('La base SQLite no es integra.')
subprocess.run(['ffmpeg', '-version'], check=True, stdout=subprocess.DEVNULL)
subprocess.run(['ffprobe', '-version'], check=True, stdout=subprocess.DEVNULL)
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="Etiqueta o ID de una imagen ya compilada")
    image = parser.parse_args().image
    docker = ["docker", "--config", os.environ.get("DOCKER_CONFIG", str(ROOT / "runtime/docker-config"))]
    name = f"armonia-smoke-{uuid.uuid4().hex}"
    container = subprocess.check_output([*docker, "run", "--pull=never", "--detach", "--name", name,
        "--network", "none", "--log-driver", "none", "--tmpfs", "/app/data:uid=1000,gid=1000",
        "--tmpfs", "/music:uid=1000,gid=1000", image], text=True).strip()
    try:
        subprocess.run([*docker, "exec", container, "python", "-c", CHECK], check=True, timeout=90)
        print("Correcto: salud, web, SQLite, FFmpeg y ffprobe.")
    finally:
        subprocess.run([*docker, "rm", "-f", container], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
