import os
from datetime import date
from pathlib import Path

import pytest

from fpvcut.core import importer
from fpvcut.core.drives import ImportSource, VolumeInfo, find_source
from fpvcut.core.importer import collect_files, folder_name, run_import
from tests.test_scanner import write


@pytest.fixture
def card(tmp_path):
    dcim = tmp_path / "card" / "DCIM"
    write(dcim / "100MEDIA" / "DJI_0001.MP4", b"a" * 1000)
    write(dcim / "100MEDIA" / "DJI_0001.SRT", b"telemetry")
    write(dcim / "100MEDIA" / "DJI_0002.MP4", b"b" * 2000)
    write(dcim / "100MEDIA" / "notes.txt", b"bleibt")
    write(dcim / "101MEDIA" / "DJI_0001.MP4", b"c" * 500)  # gleicher Name, anderer Inhalt
    write(dcim / "101MEDIA" / "DJI_0001.SRT", b"telemetry 2")
    return dcim


def test_folder_name_follows_scheme():
    assert folder_name(date(2026, 10, 23), "Wiese") == "2026-10-23_Wiese"
    assert folder_name(date(2026, 10, 23), "  ") == "2026-10-23"
    assert folder_name(date(2026, 10, 23), 'Feld: "Nord"/Süd.') == "2026-10-23_Feld- -Nord--Süd"


def test_collect_files_takes_videos_and_sidecars(card):
    names = [p.relative_to(card).as_posix() for p in collect_files(card)]
    assert names == ["100MEDIA/DJI_0001.MP4", "100MEDIA/DJI_0001.SRT", "100MEDIA/DJI_0002.MP4",
                     "101MEDIA/DJI_0001.MP4", "101MEDIA/DJI_0001.SRT"]


def test_import_copies_checks_and_deletes(card, tmp_path):
    target = tmp_path / "FPV" / "2026-10-23_Wiese"
    seen = []
    result = run_import(collect_files(card), target, delete_source=True,
                        progress=lambda done, total, name: seen.append((done, total)))
    assert result.complete and result.deleted == 5
    assert sorted(p.name for p in target.iterdir()) == [
        "DJI_0001.MP4", "DJI_0001.SRT", "DJI_0001_1.MP4", "DJI_0001_1.SRT", "DJI_0002.MP4"]
    assert (target / "DJI_0001_1.MP4").read_bytes() == b"c" * 500
    assert (target / "DJI_0001_1.SRT").read_bytes() == b"telemetry 2"  # folgt dem umbenannten Video
    assert seen[-1] == (3520, 3520)
    # Auf der Karte bleibt nur, was nicht importiert wurde; die Ordner bleiben stehen.
    assert [p.name for p in card.rglob("*") if p.is_file()] == ["notes.txt"]
    assert (card / "101MEDIA").is_dir()


def test_import_keeps_recording_time(card, tmp_path):
    source = card / "100MEDIA" / "DJI_0002.MP4"
    os.utime(source, (1_700_000_000, 1_700_000_000))
    run_import([source], tmp_path / "out", delete_source=False)
    assert (tmp_path / "out" / "DJI_0002.MP4").stat().st_mtime == 1_700_000_000


def test_second_import_recognizes_existing_files(card, tmp_path):
    target = tmp_path / "out"
    files = collect_files(card)
    run_import(files, target, delete_source=False)
    result = run_import(files, target, delete_source=True)
    assert not result.copied and len(result.already_there) == 5 and result.deleted == 5
    assert len(list(target.iterdir())) == 5


def test_failed_check_keeps_file_on_card(card, tmp_path, monkeypatch):
    real_hash = importer.hash_file
    bad = card / "100MEDIA" / "DJI_0002.MP4"
    monkeypatch.setattr(importer, "hash_file",
                        lambda path, *a: "kaputt" if path.name.startswith("DJI_0002") else real_hash(path, *a))
    result = run_import(collect_files(card), tmp_path / "out", delete_source=True)
    assert not result.complete and len(result.errors) == 1 and "DJI_0002" in result.errors[0]
    assert bad.exists() and result.deleted == 4
    assert not list((tmp_path / "out").glob("DJI_0002*"))  # weder Kopie noch .part


def test_cancel_deletes_nothing_and_leaves_no_part_files(card, tmp_path):
    calls = []

    def cancelled():
        calls.append(1)
        return len(calls) > 3

    result = run_import(collect_files(card), tmp_path / "out", delete_source=True, cancelled=cancelled)
    assert result.cancelled and result.deleted == 0
    assert len([p for p in card.rglob("*") if p.is_file()]) == 6
    assert not list((tmp_path / "out").glob("*.part"))


def test_same_file_is_never_deleted(card):
    folder = card / "100MEDIA"
    result = run_import(collect_files(folder), folder, delete_source=True)
    assert result.deleted == 0 and len(result.errors) == 3
    assert (folder / "DJI_0001.MP4").exists()


# --- SD-Karte wiederfinden --------------------------------------------------

def _drives(tmp_path, layout):
    """Laufwerke als Ordner im Testverzeichnis: {"E:\\": (VolumeInfo, wechselbar, hat DCIM)}."""
    paths = {}
    for letter, (_info, _removable, has_folder) in layout.items():
        base = tmp_path / letter[0]
        if has_folder:
            (base / "DCIM" / "100MEDIA").mkdir(parents=True)
        else:
            base.mkdir()
        paths[letter] = str(base) + os.sep
    source = lambda drive: ImportSource(drive, "DCIM\\100MEDIA" if os.sep == "\\" else "DCIM/100MEDIA")  # noqa: E731
    return (
        lambda: list(paths.values()),
        lambda d: next(layout[k][0] for k, v in paths.items() if v == d),
        lambda d: next(layout[k][1] for k, v in paths.items() if v == d),
        paths, source,
    )


def test_find_source_prefers_same_card(tmp_path):
    drives, info, removable, paths, source = _drives(tmp_path, {
        "E:\\": (VolumeInfo("SD", 1), True, True),
        "F:\\": (VolumeInfo("SD", 2), True, True),
        "G:\\": (VolumeInfo("OTHER", 3), True, False),
    })
    remembered = source(paths["E:\\"])
    remembered.label, remembered.serial = "SD", 2
    assert find_source(remembered, drives, info, removable) == Path(paths["F:\\"]) / remembered.subfolder
    remembered.serial = 99  # neu formatiert: gleiche Bezeichnung reicht
    remembered.drive = paths["G:\\"]
    assert find_source(remembered, drives, info, removable) == Path(paths["E:\\"]) / remembered.subfolder


def test_find_source_ignores_fixed_disks_and_empty_readers(tmp_path):
    drives, info, removable, paths, source = _drives(tmp_path, {
        "C:\\": (VolumeInfo("", 1), False, True),
        "E:\\": (None, True, False),  # Kartenleser ohne Karte
    })
    assert find_source(source(paths["E:\\"]), drives, info, removable) is None
    # Eine Festplatte nur, wenn genau sie gemerkt ist.
    assert find_source(source(paths["C:\\"]), drives, info, removable) is not None


def test_import_source_round_trip():
    src = ImportSource("E:\\", "DCIM\\100MEDIA", "SD", 42)
    assert ImportSource.from_dict(src.to_dict()) == src
    assert ImportSource.from_dict({"bogus": 1}) is None
    parsed = ImportSource.for_folder("E:\\DCIM\\100MEDIA")
    assert (parsed.drive, parsed.subfolder) == ("E:\\", "DCIM\\100MEDIA")


# --- Dialog -----------------------------------------------------------------

def test_import_dialog_remembers_source_and_imports(monkeypatch, tmp_path, card):
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtCore import QThreadPool

    from fpvcut.core import drives
    from fpvcut.ui import import_dialog, player
    from fpvcut.ui.main_window import MainWindow

    monkeypatch.setattr(player, "load_mpv", lambda: (None, "test"))
    monkeypatch.setattr(MainWindow, "rescan_library", lambda self: None)
    ejected = []
    monkeypatch.setattr(drives, "eject", ejected.append)
    # Testordner statt echter Laufwerke: die „Karte“ liegt auf dem gemerkten Laufwerk.
    monkeypatch.setattr(drives, "find_source", lambda source: source.path if source.path.is_dir() else None)
    window = MainWindow(db_path=tmp_path / "lib.sqlite")
    library_root = tmp_path / "FPV"
    library_root.mkdir()
    window.library.add_root(library_root)

    dialog = window.import_dialog()
    assert dialog.source is None and not dialog._start.isEnabled()
    dialog.remember_source(card)
    assert len(dialog.files) == 5 and "3 Videos" in dialog._source_label.text()
    dialog._eject.setChecked(True)
    dialog._spot.setText("Wiese")
    assert dialog.target_dir().name == f"{date.today():%Y-%m-%d}_Wiese"
    assert dialog.start(confirm=False)
    QThreadPool.globalInstance().waitForDone(10000)
    QtWidgets.QApplication.processEvents()
    assert dialog.result.complete and dialog.result.deleted == 5
    assert len(list((library_root / f"{date.today():%Y-%m-%d}_Wiese").iterdir())) == 5
    assert ejected == [card.anchor] or card.anchor.upper() == str(library_root.anchor).upper()
    assert "kopiert und geprüft" in dialog._status.text()
    dialog.accept()

    # Beim nächsten Mal ist die Quelle schon da, auch die Häkchen sind gemerkt.
    write(card / "100MEDIA" / "DJI_0003.MP4", b"d" * 10)
    dialog = window.import_dialog()
    assert dialog.source == card and len(dialog.files) == 1
    assert dialog._delete.isChecked() and dialog._eject.isChecked()
    dialog.reject()
    window.close()
