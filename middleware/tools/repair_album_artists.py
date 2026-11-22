"""Repair albums split by collaborators in files that were imported before the fix.

Those files have ALBUMARTIST equal to the whole artist text of the song ("Ana, Luis"),
so every combination of performers became an album of its own. This tool proposes the
album artist that makes each song rejoin its album, and changes nothing else.

By default it only *simulates*. Nothing is guessed from commas alone:

  seguro    another song of the same album title has, as its whole album artist, exactly
            the leading name(s) of this one. The album already exists; the song rejoins it.
  probable  the leading name exists alone somewhere in this library, but not in this album.
            Listed for review; applied only with --incluir-probables.
  (the rest is reported as "sin evidencia" and never touched: «Trío Uno, Dos & Tres».)

Usage:
    python -m tools.repair_album_artists RAÍZ [--informe plan.json]              # simulation
    python -m tools.repair_album_artists RAÍZ --aplicar --copia copia.json       # writes ALBUMARTIST
    python -m tools.repair_album_artists RAÍZ --restaurar copia.json             # undoes it

Only the ALBUMARTIST tag is written; title, artist text, audio and file names stay as
they are. Each file is rewritten as a copy that replaces the original atomically, and
the previous value of every changed file is saved first in --copia. Run a Navidrome
scan afterwards. RAÍZ is one user's library folder.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from mutagen import File as MutagenFile

AUDIO_EXTENSIONS = {".m4a", ".mp3", ".flac", ".opus", ".ogg", ".webm", ".wav", ".aac", ".wma", ".aiff"}
SEPARATOR = ", "


def read(path: Path) -> dict | None:
    """artist, album artist and album of a file, as text; None when it has no readable tags."""
    try:
        audio = MutagenFile(str(path), easy=True)
    except Exception:
        return None
    if audio is None or audio.tags is None:
        return None

    def first(key):
        try:
            value = audio.tags.get(key) or [""]
        except Exception:
            value = [""]
        return str(value[0]).strip()
    return {"artist": first("artist"), "albumartist": first("albumartist"), "album": first("album")}


def scan(root: Path) -> list[dict]:
    files = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in AUDIO_EXTENSIONS or path.is_symlink() or not path.is_file():
            continue
        tags = read(path)
        if tags:
            files.append({"path": str(path.relative_to(root)), **tags})
    return files


def prefixes(name: str) -> list[str]:
    """Leading parts of "A, B, C" cut only at ", ": ["A", "A, B"]. Shortest first."""
    parts = name.split(SEPARATOR)
    return [SEPARATOR.join(parts[:n]) for n in range(1, len(parts))]


def plan(files: list[dict]) -> dict:
    """What would change, with the evidence for each file. Pure: reads nothing, writes nothing."""
    fold = str.casefold
    by_album = defaultdict(dict)  # album title -> {folded album artist: as written}
    alone = {}                    # every whole artist / album artist text in the library
    for f in files:
        if f["albumartist"]:
            by_album[fold(f["album"])].setdefault(fold(f["albumartist"]), f["albumartist"])
            alone.setdefault(fold(f["albumartist"]), f["albumartist"])
        if f["artist"]:
            alone.setdefault(fold(f["artist"]), f["artist"])
    changes, untouched = [], []
    for f in files:
        current = f["albumartist"]
        # The signature of the old import: the album artist is the song's whole artist text.
        if SEPARATOR not in current or fold(current) != fold(f["artist"]):
            continue
        owners = by_album[fold(f["album"])]
        sure = next((owners[fold(p)] for p in prefixes(current) if fold(p) in owners), None)
        likely = next((alone[fold(p)] for p in prefixes(current) if fold(p) in alone), None)
        if sure:
            changes.append({**f, "to": sure, "evidence": "seguro"})
        elif likely:
            changes.append({**f, "to": likely, "evidence": "probable"})
        else:
            untouched.append(f)

    def albums(selected):
        moved = {c["path"]: c["to"] for c in changes if c["evidence"] in selected}
        return len({(fold(moved.get(f["path"], f["albumartist"])), fold(f["album"])) for f in files})

    def artists(selected):
        moved = {c["path"]: c["to"] for c in changes if c["evidence"] in selected}
        return len({fold(moved.get(f["path"], f["albumartist"])) for f in files})
    return {
        "files": len(files),
        "changes": changes,
        "without_evidence": untouched,
        "albums": {"before": albums(()), "after_sure": albums(("seguro",)), "after_all": albums(("seguro", "probable"))},
        "album_artists": {"before": artists(()), "after_sure": artists(("seguro",)), "after_all": artists(("seguro", "probable"))},
    }


def write_album_artist(path: Path, value: str) -> None:
    """Rewrite one tag on a copy and swap it in, so an interruption never leaves half a file."""
    handle, name = tempfile.mkstemp(prefix=".repair-", suffix=path.suffix, dir=path.parent)
    os.close(handle)
    temporary = Path(name)
    try:
        shutil.copy2(path, temporary)
        audio = MutagenFile(str(temporary), easy=True)
        audio["albumartist"] = value
        audio.save()
        check = read(temporary)
        if not check or check["albumartist"] != value:
            raise RuntimeError("the tag could not be verified after writing")
        with open(temporary, "rb") as written:
            os.fsync(written.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply(root: Path, proposed: dict, backup: Path, include_likely: bool) -> dict:
    selected = [c for c in proposed["changes"] if c["evidence"] == "seguro" or include_likely]
    record = {"root": str(root), "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "entries": [{"path": c["path"], "before": c["albumartist"], "after": c["to"]} for c in selected]}
    # The way back exists on disk before the first file is touched.
    with open(backup, "x", encoding="utf-8") as out:
        json.dump(record, out, ensure_ascii=False, indent=1)
        out.flush()
        os.fsync(out.fileno())
    done, failed = 0, []
    for change in selected:
        try:
            write_album_artist(root / change["path"], change["to"])
            done += 1
        except Exception as exc:
            failed.append({"path": change["path"], "error": str(exc)})
    return {"changed": done, "failed": failed}


def restore(root: Path, backup: Path) -> dict:
    record = json.loads(backup.read_text(encoding="utf-8"))
    restored, skipped = 0, []
    for entry in record["entries"]:
        path = root / entry["path"]
        tags = read(path) if path.is_file() and not path.is_symlink() else None
        if not tags:
            skipped.append({"path": entry["path"], "reason": "missing"})
        elif tags["albumartist"] == entry["before"]:
            continue
        elif tags["albumartist"] != entry["after"]:
            skipped.append({"path": entry["path"], "reason": "changed since the repair"})
        else:
            write_album_artist(path, entry["before"])
            restored += 1
    return {"restored": restored, "skipped": skipped}


def describe(proposed: dict, out=sys.stdout) -> None:
    groups = defaultdict(list)
    for change in proposed["changes"]:
        groups[(change["evidence"], change["album"], change["to"])].append(change)
    for evidence in ("seguro", "probable"):
        chosen = sorted((key, rows) for key, rows in groups.items() if key[0] == evidence)
        print(f"\n== {evidence.upper()}: {sum(len(rows) for _, rows in chosen)} canciones en {len(chosen)} álbumes ==", file=out)
        for (_, album, to), rows in chosen:
            print(f"«{album}» → artista del álbum «{to}»", file=out)
            for row in rows:
                print(f"    antes «{row['albumartist']}»   {row['path']}", file=out)
    print(f"\n== SIN EVIDENCIA (no se tocan): {len(proposed['without_evidence'])} ==", file=out)
    for row in proposed["without_evidence"]:
        print(f"    «{row['albumartist']}» · «{row['album']}»   {row['path']}", file=out)
    a, b = proposed["albums"], proposed["album_artists"]
    print(f"\nArchivos leídos: {proposed['files']}", file=out)
    print(f"Álbumes: {a['before']} ahora → {a['after_sure']} aplicando «seguro» → {a['after_all']} con «probable»", file=out)
    print(f"Artistas de álbum: {b['before']} ahora → {b['after_sure']} → {b['after_all']}", file=out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Reúne álbumes partidos por colaboradores (simula por defecto).")
    parser.add_argument("root", type=Path)
    parser.add_argument("--informe", type=Path, help="guarda el plan completo en JSON")
    parser.add_argument("--aplicar", action="store_true", help="escribe ALBUMARTIST (exige --copia)")
    parser.add_argument("--copia", type=Path, help="archivo nuevo donde guardar los valores anteriores")
    parser.add_argument("--incluir-probables", action="store_true")
    parser.add_argument("--restaurar", type=Path, help="deshace una reparación con su archivo de copia")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        parser.error("la raíz no es una carpeta")
    if args.restaurar:
        print(json.dumps(restore(root, args.restaurar), ensure_ascii=False, indent=1))
        return 0
    proposed = plan(scan(root))
    describe(proposed)
    if args.informe:
        args.informe.write_text(json.dumps(proposed, ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.aplicar:
        print("\nSimulación: no se ha escrito nada. Para aplicar: --aplicar --copia ARCHIVO_NUEVO")
        return 0
    if not args.copia:
        parser.error("--aplicar exige --copia")
    result = apply(root, proposed, args.copia, args.incluir_probables)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    print("Lanza ahora un escaneo de Navidrome. Para deshacer: --restaurar", args.copia)
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
