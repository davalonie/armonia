"""Laboratorio: canciones ficticias del tamaño de las reales para medir datos y arranque.

Como la biblioteca real (18-11-2026): AAC-LC 128 kbit/s estereo, 3:20-4:30, con una caratula grande incrustada
(~500 KB, la mediana real es 456-519 KB). Ruido rosa mas un tono: se comprime como la musica, no como un tono puro.
Album «Datos» de «Medicion Datos», cuenta ficticia «ana». Solo se crean si faltan.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

FOLDER = lab.MUSIC / "Medición Datos"
DURATIONS = [200, 215, 230, 245, 255, 262, 238, 270]


def make(scan=True):
    from mutagen.mp4 import MP4, MP4Cover
    FOLDER.mkdir(parents=True, exist_ok=True)
    made = False
    for n, seconds in enumerate(DURATIONS, 1):
        target = FOLDER / f"Medición Datos - Tema {n}.m4a"
        if target.exists():
            continue
        cover = FOLDER / f".portada-{n}.jpg"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"nullsrc=s=1200x1200,geq=random(1)*{90 + n * 15}:128+{n * 9}*sin(X/40):{60 + n * 20}",
                        "-frames:v", "1", "-q:v", "3", str(cover)], check=True)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"anoisesrc=d={seconds}:c=pink:a=0.25",
                        "-f", "lavfi", "-i", f"sine=f={180 + n * 45}:d={seconds}", "-filter_complex", "amix=inputs=2,aformat=channel_layouts=stereo",
                        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(target)], check=True)
        audio = MP4(str(target))
        audio["\xa9ART"], audio["\xa9nam"], audio["\xa9alb"], audio["aART"] = "Medición Datos", f"Tema {n}", "Datos", "Medición Datos"
        audio["covr"] = [MP4Cover(cover.read_bytes(), imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()
        cover.unlink()
        made = True
    if made and scan:
        lab.scan(full=True)
    for f in sorted(FOLDER.glob("*.m4a")):
        print(f.name, round(f.stat().st_size / 1e6, 2), "MB")


if __name__ == "__main__":
    make()
