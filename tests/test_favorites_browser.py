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
    assert panel._summary.text().startswith("1 von 3 Ausschnitten")

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


def test_tag_area_grows_with_tags_and_can_be_dragged():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from fpvcut.ui.favorites_panel import FavoritesPanel

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    panel = FavoritesPanel()
    panel.resize(370, 700)
    panel.show()
    panel.set_data([], [("Crash", 1), ("Flip", 2)])
    app.processEvents()
    row = panel._tags.row_height()
    one_row = panel._splitter.sizes()[0]
    assert one_row < 2 * row  # nur eine Zeile

    panel.set_data([], [(f"Tag{i}", i) for i in range(40)])
    app.processEvents()
    grown = panel._splitter.sizes()[0]
    assert grown > 3 * row + 10  # mehr als die früheren drei Zeilen
    assert grown <= 8 * row  # aber gedeckelt, danach wird gescrollt

    # Von Hand gezogen: die Höhe bleibt, auch wenn sich die Tags ändern.
    panel._splitter.setSizes([100, 500])
    panel._on_splitter_moved(100, 1)
    panel.set_data([], [("Crash", 1)])
    app.processEvents()
    assert panel._splitter.sizes()[0] == 100
    panel.close()


def test_tag_area_fits_when_tab_is_opened_later():
    """Beim Start liegt der Browser in einem verdeckten Reiter; beim ersten Öffnen muss das Feld passen."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from fpvcut.ui.favorites_panel import FavoritesPanel

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tabs = QtWidgets.QTabWidget()
    panel = FavoritesPanel()
    tabs.addTab(QtWidgets.QLabel("Bibliothek"), "Bibliothek")
    tabs.addTab(panel, "Favoriten")
    panel.set_data([], [(f"Tag{i}", i) for i in range(40)])
    tabs.resize(370, 700)
    tabs.show()
    app.processEvents()
    tabs.setCurrentIndex(1)
    app.processEvents()
    assert panel._splitter.sizes()[0] > 3 * panel._tags.row_height()
    tabs.close()


def test_star_column_toggles_favorite(monkeypatch, tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtCore import Qt

    from fpvcut.ui import player
    from fpvcut.ui.favorites_panel import COL_STAR, COL_TITLE
    from fpvcut.ui.main_window import MainWindow

    make_lib(tmp_path).close()
    monkeypatch.setattr(player, "load_mpv", lambda: (None, "test"))
    monkeypatch.setattr(MainWindow, "rescan_library", lambda self: None)
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(db_path=tmp_path / "lib.sqlite")
    panel = window.favorites_panel

    def first():
        return panel._tree.topLevelItem(0)

    clip_id = first().data(0, Qt.ItemDataRole.UserRole)[0].id
    panel._on_clicked(first(), COL_TITLE)  # Klick auf den Titel schaltet nicht um
    assert not any(c.favorite for c, _ in window.library.all_clips())
    panel._on_clicked(first(), COL_STAR)
    assert [c.id for c, _ in window.library.all_clips() if c.favorite] == [clip_id]
    assert first().text(COL_STAR) == "★"

    panel._favorites_only.setChecked(True)
    assert panel._tree.topLevelItemCount() == 1
    panel.reset_filter()
    assert panel._tree.topLevelItemCount() == 3

    library_item = window.library_panel._tree.topLevelItem(0).child(0)
    assert "davon 1 Favorit" in library_item.data(0, Qt.ItemDataRole.AccessibleTextRole)
    window.close()
