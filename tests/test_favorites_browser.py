import os

import pytest

from fpvcut.core.clip_filter import clip_duration, clip_matches, filter_clips
from fpvcut.core.library import Library
from fpvcut.core.scanner import scan_library
from tests.test_scanner import fake_probe, write


def make_lib(tmp_path):
    """Zwei Flugtage mit je einem Video und ein paar Favoriten."""
    root = tmp_path / "FPV"
    write(root / "2026_08_28_Wiese" / "alt.mp4", b"aaa")
    write(root / "2026_09_14_Steinbruch" / "neu.mp4", b"bbb")
    lib = Library(tmp_path / "lib.sqlite")
    lib.add_root(root)
    scan_library(lib, fake_probe)
    ids = {e.path.name: e.media_id for e in lib.entries()}
    lib.add_clip(ids["alt.mp4"], 200, 800, ["Flip", "Gap"], "knapp am Baum")
    lib.add_clip(ids["neu.mp4"], 500, None, ["Flip"])
    lib.add_clip(ids["neu.mp4"], 0, 300, ["Crash"])
    return lib


def test_all_clips_and_tag_counts(tmp_path):
    lib = make_lib(tmp_path)
    items = lib.all_clips()
    assert len(items) == 3
    assert all(clip.media_id == entry.media_id for clip, entry in items)
    assert lib.tag_counts() == [("Flip", 2), ("Crash", 1), ("Gap", 1)]
    lib.close()


def test_filter_by_tags_and_text(tmp_path):
    lib = make_lib(tmp_path)
    items = lib.all_clips()

    def names(result):
        return [(e.path.name, c.in_ms) for c, e in result]

    # Ohne Filter: neuester Flugtag zuerst, im Video nach Zeit.
    assert names(filter_clips(items, [])) == [("neu.mp4", 0), ("neu.mp4", 500), ("alt.mp4", 200)]
    assert names(filter_clips(items, ["flip"])) == [("neu.mp4", 500), ("alt.mp4", 200)]
    assert names(filter_clips(items, ["Flip", "Crash"])) == [("neu.mp4", 0), ("neu.mp4", 500), ("alt.mp4", 200)]
    assert names(filter_clips(items, ["Flip", "Gap"], match_all=True)) == [("alt.mp4", 200)]
    assert names(filter_clips(items, [], text="baum")) == [("alt.mp4", 200)]
    assert names(filter_clips(items, [], text="steinbruch crash")) == [("neu.mp4", 0)]
    clip, entry = items[0]
    assert clip_matches(clip, entry, [], text="")
    lib.close()


def test_clip_duration_uses_video_length_for_open_end(tmp_path):
    lib = make_lib(tmp_path)
    durations = {(e.path.name, c.in_ms): clip_duration(c, e) for c, e in lib.all_clips()}
    assert durations[("alt.mp4", 200)] == pytest.approx(0.6)
    assert durations[("neu.mp4", 500)] == pytest.approx(0.5)  # bis zum Ende (fake_probe: 1 s)
    lib.close()


def test_favorites_panel_filters_and_plays(monkeypatch, tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from fpvcut.ui import player
    from fpvcut.ui.main_window import MainWindow

    make_lib(tmp_path).close()
    monkeypatch.setattr(player, "load_mpv", lambda: (None, "test"))
    monkeypatch.setattr(MainWindow, "rescan_library", lambda self: None)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(db_path=tmp_path / "lib.sqlite")
    panel = window.favorites_panel
    assert panel._tree.topLevelItemCount() == 3
    assert [b.text() for b in panel._tag_buttons.values()] == ["Flip (2)", "Crash (1)", "Gap (1)"]

    # Jeder Klick schaltet um, auch zwei schnell hintereinander (Doppelklick).
    crash = panel._tag_buttons["Crash"]
    QTest.mouseClick(crash, Qt.MouseButton.LeftButton)
    assert panel.selected_tags() == ["Crash"]
    QTest.mouseClick(crash, Qt.MouseButton.LeftButton)
    assert panel.selected_tags() == []
    QTest.mouseClick(crash, Qt.MouseButton.LeftButton)
    assert panel.selected_tags() == ["Crash"]
    assert panel.selected_tags() == ["Crash"]
    assert panel._tree.topLevelItemCount() == 1
    assert panel._summary.text().startswith("1 von 3 Favoriten")

    # Doppelklick öffnet das Video mit dem Ausschnitt als Auswahl.
    item = panel._tree.topLevelItem(0)
    clip = item.data(0, Qt.ItemDataRole.UserRole)[0]
    panel._on_activated(item, 0)
    assert window.current_entry.path.name == "neu.mp4"
    assert (window.player.in_point, window.player.out_point) == (0.0, 0.3)

    # Nach dem Löschen verschwindet der Tag samt Favorit, die Filterauswahl der anderen bleibt.
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *a: QtWidgets.QMessageBox.StandardButton.Yes)
    window.delete_clip(clip)
    assert panel.selected_tags() == []
    assert panel._tree.topLevelItemCount() == 2

    panel.reset_filter()
    panel._search.setText("wiese")
    assert panel._tree.topLevelItemCount() == 1
    app.processEvents()
    window.close()
