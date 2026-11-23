"""The repair of albums split by collaborators: evidence, simulation, backup and way back. Fictitious names."""
import json
import shutil
import subprocess

import pytest

from tools import repair_album_artists as repair


def song(path, artist, album, albumartist=None):
    return {"path": path, "artist": artist, "album": album, "albumartist": artist if albumartist is None else albumartist}


LIBRARY = [
    song("a1", "Lúa Norte", "Mareas"), song("a2", "Lúa Norte", "Mareas"),
    song("a3", "Lúa Norte, Vera Solano", "Mareas"), song("a4", "Lúa Norte, Vera Solano, Faro Sur", "Mareas"),
    song("b1", "Otro Grupo", "Mareas"),
    song("c1", "Lúa Norte", "Mareas (En directo)"),
    song("d1", "Trío Uno, Dos & Tres", "Primer acto"), song("d2", "Trío Uno, Dos & Tres, Invitada", "Primer acto"),
    song("e1", "Faro Sur, Bruma Clara", "Disco sin dueño"),   # «Faro Sur» exists alone, but not in this album
    song("f1", "Ana, Luis", "Dúo"),                           # nobody called «Ana» anywhere
    song("g1", "Vera Solano", "Postales"), song("g2", "Faro Sur", "Invierno"),
    song("h1", "Solista, Invitado", "Recopilatorio", "Varios Artistas"),  # tagged by hand: not the old signature
    song("i1", "Tierra", "Raíces"), song("i2", "Tierra, Viento y Fuego", "Otro disco"),
]


def test_only_songs_with_an_existing_album_are_sure_and_names_with_commas_survive():
    proposed = repair.plan(LIBRARY)
    changes = {c["path"]: (c["to"], c["evidence"]) for c in proposed["changes"]}
    assert changes["a3"] == changes["a4"] == ("Lúa Norte", "seguro")
    # The comma inside the trio's name is kept: the song rejoins the trio's album, not «Trío Uno».
    assert changes["d2"] == ("Trío Uno, Dos & Tres", "seguro") and "d1" not in changes
    assert changes["e1"] == ("Faro Sur", "probable")
    # A band whose name starts like another artist is only ever "probable", never applied by default.
    assert changes["i2"] == ("Tierra", "probable")
    assert set(changes) == {"a3", "a4", "d2", "e1", "i2"}
    assert {f["path"] for f in proposed["without_evidence"]} == {"d1", "f1"}
    # Same title, another owner or another edition: never merged.
    assert proposed["albums"]["before"] - proposed["albums"]["after_sure"] == 3
    keys = {(c["to"], c["album"]) for c in proposed["changes"]} | {(f["albumartist"], f["album"]) for f in LIBRARY if f["path"] in ("b1", "c1")}
    assert ("Otro Grupo", "Mareas") in keys and ("Lúa Norte", "Mareas (En directo)") in keys


def test_the_plan_is_empty_for_a_library_tagged_by_the_corrected_import():
    fixed = [song("a1", "Lúa Norte", "Mareas"), song("a3", "Lúa Norte, Vera Solano", "Mareas", "Lúa Norte")]
    proposed = repair.plan(fixed)
    assert proposed["changes"] == [] and proposed["albums"]["before"] == proposed["albums"]["after_all"] == 1


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg unavailable")
def test_simulation_writes_nothing_and_apply_can_be_undone(tmp_path, capsys):
    from mutagen import File

    root = tmp_path / "library"
    files = {"Lúa Norte/solo.m4a": "Lúa Norte", "Lúa Norte, Vera Solano/dueto.m4a": "Lúa Norte, Vera Solano",
             "Faro Sur, Bruma Clara/otro.mp3": "Faro Sur, Bruma Clara", "Faro Sur/suyo.mp3": "Faro Sur"}
    for name, artist in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=0.3", str(path)], check=True)
        audio = File(str(path), easy=True)
        audio["artist"], audio["albumartist"], audio["title"] = artist, artist, path.stem
        audio["album"] = "Mareas" if name.endswith("m4a") else ("Invierno" if "suyo" in name else "Otro disco")
        audio.save()
    (root / "enlace.m4a").symlink_to(root / "Lúa Norte/solo.m4a")  # never followed
    before = {name: (root / name).read_bytes() for name in files}

    assert repair.main([str(root)]) == 0
    assert "Simulacion: no se ha escrito nada" in capsys.readouterr().out
    assert {name: (root / name).read_bytes() for name in files} == before

    backup = tmp_path / "copia.json"
    with pytest.raises(SystemExit):
        repair.main([str(root), "--aplicar"])  # no way back, no writing
    assert repair.main([str(root), "--aplicar", "--copia", str(backup)]) == 0
    tags = {name: repair.read(root / name) for name in files}
    assert tags["Lúa Norte, Vera Solano/dueto.m4a"] == {"artist": "Lúa Norte, Vera Solano", "albumartist": "Lúa Norte", "album": "Mareas"}
    assert tags["Faro Sur, Bruma Clara/otro.mp3"]["albumartist"] == "Faro Sur, Bruma Clara"  # only "probable": untouched
    assert [e["path"] for e in json.loads(backup.read_text())["entries"]] == ["Lúa Norte, Vera Solano/dueto.m4a"]
    assert not list(root.rglob(".repair-*"))
    with pytest.raises(FileExistsError):
        repair.apply(root, repair.plan(repair.scan(root)), backup, False)  # a backup is never overwritten

    assert repair.restore(root, backup) == {"restored": 1, "skipped": []}
    assert repair.read(root / "Lúa Norte, Vera Solano/dueto.m4a")["albumartist"] == "Lúa Norte, Vera Solano"
    assert repair.restore(root, backup) == {"restored": 0, "skipped": []}  # idempotent
    # A file edited by its owner after the repair is left alone when undoing.
    repair.write_album_artist(root / "Lúa Norte, Vera Solano/dueto.m4a", "Elegido a mano")
    assert repair.restore(root, backup)["skipped"] == [{"path": "Lúa Norte, Vera Solano/dueto.m4a", "reason": "changed since the repair"}]
