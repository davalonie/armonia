"""Two listeners in one application container; fail together, stop gracefully."""
import os
import signal
import subprocess
import sys
import time

children = []
stopping = False


def stop(signum, frame):
    global stopping
    stopping = True
    for p in children:
        p.terminate()


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    for module, port in (("main:app", "8000"), ("internal_main:app", "8001")):
        children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", module,
            "--host", "0.0.0.0", "--port", port, "--no-proxy-headers", "--no-access-log"]))
    if os.environ.get("MUSIC_METADATA_PROXY_ENABLED") == "true":
        children.append(subprocess.Popen([sys.executable, "-m", "homelab.metadata_proxy"]))
    while all(p.poll() is None for p in children):
        time.sleep(.25)
    failed = not stopping
finally:
    stop(None, None)
    for p in children:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
sys.exit(1 if failed else 0)
