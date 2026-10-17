import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt  # noqa: E402

from fpvcut.core.scanner import scan_library  # noqa: E402
from fpvcut.timeline.model import Timeline, TimelineClip  # noqa: E402
from tests.test_scanner import fake_probe, write  # noqa: E402


def test_rename_dialog_renames_and_window_follows(monkeypatch, tmp_path):
    from fpvcut.ui import player
    from fpvcut.ui.main_window import MainWindow

    root = tmp_path / "FPV"
    write(root / "28_08_26_Wiese" / "a.mp4", b"aaa")
    write(root / "12_08_15_Feld" / "b.mp4", b"bbb")  # zweideutig
    write(root / "Sonstiges" / "c.mp4", b"ccc")
    monkeypatch.setattr(player, "load_mpv", lambda: (None, "test"))
    monkeypatch.setattr(MainWindow, "rescan_library", lambda self: None)
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(db_path=tmp_path / "lib.sqlite")
    window.library.add_root(root)
    scan_library(window.library, fake_probe)
    entry = next(e for e in window.library.entries() if e.path.name == "a.mp4")
    window.timeline_panel.set_timeline(window.resolve_timeline(
        Timeline([TimelineClip(entry.fingerprint, 0, 1, 1, "a.mp4")])))

    dialog = window.rename_dialog()
    table = dialog.table
    assert table.rowCount() == 3
    rows = {table.item(r, 1).text(): r for r in range(table.rowCount())}
    assert table.item(rows["28_08_26_Wiese"], 2).text() == "2026_08_28_Wiese"
    assert table.item(rows["28_08_26_Wiese"], 0).checkState() == Qt.CheckState.Checked
    assert table.item(rows["12_08_15_Feld"], 0).checkState() == Qt.CheckState.Unchecked
    assert "Prüfen" in table.item(rows["12_08_15_Feld"], 3).text()
    dialog.set_new_name("Sonstiges", "2026_05_01_Sonstiges")  # Name von Hand
    assert dialog._apply.text() == "2 Ordner umbenennen"

    result = dialog.apply(confirm=False)
    assert len(result.done) == 2 and not result.errors
    assert (root / "2026_08_28_Wiese" / "a.mp4").exists()
    assert (root / "2026_05_01_Sonstiges" / "c.mp4").exists()
    log = next((tmp_path / "umbenannt").glob("*.json"))
    assert len(json.loads(log.read_text(encoding="utf-8"))) == 2
    dialog.accept()
    QtWidgets.QApplication.processEvents()
    # Bibliothek und Timeline zeigen die neuen Pfade.
    assert window.timeline_panel.timeline.clips[0].path == root / "2026_08_28_Wiese" / "a.mp4"

    dialog = window.rename_dialog()
    assert dialog.table.rowCount() == 1  # nur noch der zweideutige Fall
    dialog._done = result.done
    dialog.undo()
    assert (root / "28_08_26_Wiese" / "a.mp4").exists() and (root / "Sonstiges" / "c.mp4").exists()
    dialog.accept()
    QtWidgets.QApplication.processEvents()
    assert window.timeline_panel.timeline.clips[0].path == root / "28_08_26_Wiese" / "a.mp4"
    window.close()
