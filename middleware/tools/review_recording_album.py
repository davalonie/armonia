"""Review an existing track's album edition, then apply exactly that saved proposal."""
import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from mutagen import File

from services import recording_album, tagger_service


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def proposal(path):
    audio = File(path, easy=True)
    if audio is None:
        raise ValueError("archivo de audio desconocido")
    fields = {k: (audio.get(k) or [""])[0] for k in ("title", "artist", "album", "albumartist")}
    if not recording_album.single_title(fields["album"], fields["title"]):
        raise ValueError("el archivo ya indica un album distinto del titulo")
    edition = recording_album.lookup(fields["title"], fields["artist"], audio.info.length)
    if not edition:
        raise ValueError("no hay una edicion de album inequivoca")
    return {"file": str(path), "sha256": digest(path), "before": fields, "proposed": edition}


def apply(path, plan, backup):
    if path.is_symlink() or str(path) != plan["file"] or digest(path) != plan["sha256"]:
        raise ValueError("el archivo ha cambiado desde la revision")
    with path.open("rb") as original, backup.open("xb") as copy:
        shutil.copyfileobj(original, copy)
        copy.flush()
        os.fsync(copy.fileno())
    edition = plan["proposed"]
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=path.suffix, delete=False) as f:
        tmp = Path(f.name)
    try:
        shutil.copy2(path, tmp)
        tags = File(tmp, easy=True)
        tags["album"] = edition["album"]
        tags["albumartist"] = edition["album_artist"]
        for k, tag in (("track", "tracknumber"), ("disc", "discnumber"), ("date", "originaldate")):
            if edition.get(k):
                tags[tag] = str(edition[k])
        tags.save()
        if File(tmp, easy=True)["album"][0] != edition["album"] or digest(path) != plan["sha256"]:
            raise ValueError("no se pudo verificar la reparacion")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--aplicar", type=Path, help="plan JSON previamente revisado")
    parser.add_argument("--copia", type=Path, help="archivo nuevo para conservar el audio original")
    args = parser.parse_args()
    if args.file.is_symlink() or not args.file.is_file() or args.file.suffix.lower() not in tagger_service.AUDIO_EXTENSIONS:
        parser.error("elige un archivo de audio local")
    path = args.file.resolve()
    if args.aplicar:
        if not args.copia:
            parser.error("--aplicar exige --copia")
        apply(path, json.loads(args.aplicar.read_text()), args.copia)
    else:
        print(json.dumps(proposal(path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
