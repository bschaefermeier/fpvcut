import json
import os
from datetime import datetime

import pytest

from fpvcut.core import backup
from fpvcut.core.library import Library
from fpvcut.core.scanner import scan_library
from tests.test_scanner import fake_probe, write


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "db" / "library.sqlite")
    yield library
    library.close()


def make_library(lib, root):
    write(root / "2026-08-28_Wiese" / "a.mp4", b"aaa")
    write(root / "2026-08-28_Wiese" / "b.mp4", b"bbb")
    lib.add_root(root)
    scan_library(lib, fake_probe)
    a, b = sorted(lib.entries(), key=lambda e: e.rel_path)
    lib.add_clip(a.media_id, 1000, 3000, ["Flip", "Crash"], "schön")
    lib.add_clip(a.media_id, 0, None, ["Ganz"])
    lib.set_reviewed([b.media_id])
    return a, b


def test_export_and_import_into_fresh_library_before_scan(lib, tmp_path):
    root = tmp_path / "FPV"
    make_library(lib, root)
    count = backup.export_to(lib, tmp_path / "sicherung.json")
    assert count == 2
    data = json.loads((tmp_path / "sicherung.json").read_text(encoding="utf-8"))
    assert data["format"] == backup.FORMAT and len(data["media"]) == 2

    # Frische Bibliothek (z. B. nach Neuinstallation): erst importieren, dann scannen.
    fresh = Library(tmp_path / "neu" / "library.sqlite")
    try:
        result = backup.import_from(fresh, tmp_path / "sicherung.json")
        assert (result.media_added, result.clips_added, result.reviewed) == (2, 2, 1)
        assert fresh.all_clips() == []  # ohne Fundort noch nicht sichtbar
        fresh.add_root(root)
        scan = scan_library(fresh, fake_probe)
        assert scan.new == 0  # per Fingerprint wiedererkannt, keine neuen Videos
        clips = fresh.all_clips()
        assert sorted((c.in_ms, c.out_ms, tuple(c.tags), c.note) for c, _ in clips) == [
            (0, None, ("Ganz",), ""), (1000, 3000, ("Crash", "Flip"), "schön")]
        entries = {e.path.name: e for e in fresh.entries()}
        assert not entries["b.mp4"].is_new and entries["a.mp4"].duration == 1.0
        # Zweiter Import verdoppelt nichts.
        again = backup.import_from(fresh, tmp_path / "sicherung.json")
        assert (again.clips_added, again.clips_skipped, again.media_added) == (0, 2, 0)
        assert len(fresh.all_clips()) == 2
    finally:
        fresh.close()


def test_import_merges_tags_and_rejects_foreign_files(lib, tmp_path):
    a, _b = make_library(lib, tmp_path / "FPV")
    data = backup.export_data(lib)
    next(c for c in data["media"][0]["clips"] if c["in_ms"] == 1000)["tags"].append("Neu")
    with lib.conn:
        lib.conn.execute("DELETE FROM clip WHERE out_ms IS NULL")
    result = backup.import_data(lib, data)
    assert (result.clips_added, result.clips_skipped) == (1, 1)
    tags = {c.in_ms: c.tags for c in lib.clips_for(a.media_id)}
    assert tags[1000] == ["Crash", "Flip", "Neu"]
    with pytest.raises(ValueError):
        backup.import_data(lib, {"format": "etwas anderes"})


def test_daily_backup_rotates_and_skips_empty_library(lib, tmp_path):
    folder = tmp_path / "sicherungen"
    assert backup.daily_backup(lib, folder) is None  # leer: nichts überschreiben
    make_library(lib, tmp_path / "FPV")
    for day in range(1, 36):
        backup.daily_backup(lib, folder, now=datetime(2026, 9, day % 30 + 1) if day <= 30 else datetime(2026, 10, day - 30))
    files = sorted(p.name for p in folder.glob("favoriten_*.json"))
    assert len(files) == backup.KEEP_DAILY
    assert files[-1] == "favoriten_2026-10-05.json"
    assert backup.latest_backup(folder).name == "favoriten_2026-10-05.json"
    assert not any(n.endswith(".tmp") for n in os.listdir(folder))
