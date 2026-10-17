import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtCore = pytest.importorskip("PySide6.QtCore")


def test_main_window_starts_without_libmpv(monkeypatch, tmp_path):
    """Das Fenster muss auch ohne libmpv starten und einen Hinweis zeigen."""
    from fpvcut.ui import player

    monkeypatch.setattr(player, "load_mpv", lambda: (None, "test"))
    from fpvcut.ui.main_window import MainWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(db_path=tmp_path / "lib.sqlite")
    window.show()
    app.processEvents()
    assert not window.player.available
    assert "libmpv" in window.player._message.text()
    window.close()


def test_fullscreen_toggle_keeps_shortcuts(monkeypatch, tmp_path):
    from fpvcut.ui import player

    monkeypatch.setattr(player, "load_mpv", lambda: (None, "test"))
    from fpvcut.ui.main_window import MainWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(db_path=tmp_path / "lib.sqlite")
    window.show()
    window.toggle_fullscreen()
    app.processEvents()
    assert window.isFullScreen()
    assert window.menuBar().isHidden()
    # Tastenkürzel hängen auch am Fenster selbst, damit sie im Vollbild greifen.
    assert any(a.shortcut().toString() == "Esc" for a in window.actions())
    window.exit_fullscreen()
    app.processEvents()
    assert not window.isFullScreen()
    assert not window.menuBar().isHidden()
    window.close()


def test_library_scan_shows_new_videos(monkeypatch, tmp_path):
    from PySide6.QtCore import QThreadPool

    from fpvcut.core.library import Library
    from fpvcut.ui import player
    from fpvcut.ui.main_window import MainWindow

    monkeypatch.setattr(player, "load_mpv", lambda: (None, "test"))
    day = tmp_path / "FPV" / "28_08_26_Wiese"
    day.mkdir(parents=True)
    (day / "a.mp4").write_bytes(b"kein echtes Video")
    db = tmp_path / "lib.sqlite"
    lib = Library(db)
    lib.add_root(tmp_path / "FPV")
    lib.close()

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(db_path=db)
    QThreadPool.globalInstance().waitForDone(10000)
    app.processEvents()

    tree = window.library_panel._tree
    assert tree.topLevelItemCount() == 1
    group = tree.topLevelItem(0)
    assert group.text(0) == "28.08.2026 · Wiese"
    assert group.text(2) == "1 neu"
    assert "a.mp4" in group.child(0).text(0)
    assert "Scan fertig: 1 neu" in window.statusBar().currentMessage()

    window.open_entry(group.child(0).data(0, QtCore.Qt.ItemDataRole.UserRole))
    assert window.library_panel._tree.topLevelItem(0).text(2) == ""
    window.close()


def _window(monkeypatch, tmp_path):
    from fpvcut.ui import player
    from fpvcut.ui.main_window import MainWindow

    monkeypatch.setattr(player, "load_mpv", lambda: (None, "test"))
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return app, MainWindow(db_path=tmp_path / "lib.sqlite")


def test_click_on_video_toggles_pause_once(monkeypatch, tmp_path):
    from PySide6.QtTest import QTest

    app, window = _window(monkeypatch, tmp_path)
    p = window.player
    toggles, doubles = [], []
    monkeypatch.setattr(p, "toggle_pause", lambda: toggles.append(1))
    p.double_clicked.connect(lambda: doubles.append(1))

    QTest.mouseClick(p._video, QtCore.Qt.MouseButton.LeftButton)
    assert len(toggles) == 1

    # Derselbe Klick zusätzlich von mpv gemeldet (Linux): zählt nicht doppelt.
    p._mpv_click.emit()
    assert len(toggles) == 1

    # Doppelklick: Vollbild-Signal erst beim Loslassen des zweiten Klicks, Pause bleibt wie vorher.
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    left = QtCore.Qt.MouseButton.LeftButton
    pos = QPointF(10, 10)
    dbl = QMouseEvent(QtCore.QEvent.Type.MouseButtonDblClick, pos, pos, left, left, QtCore.Qt.KeyboardModifier.NoModifier)
    QtWidgets.QApplication.sendEvent(p._video, dbl)
    assert doubles == []
    QTest.mouseRelease(p._video, left, pos=pos.toPoint())
    p._mpv_double.emit()  # dasselbe von mpv gemeldet: zählt nicht doppelt
    assert len(doubles) == 1
    assert len(toggles) % 2 == 0
    window.close()


def test_mark_whole_flight_day_reviewed(monkeypatch, tmp_path):
    from PySide6.QtCore import QThreadPool

    from fpvcut.core.library import Library

    day = tmp_path / "FPV" / "2026_08_28_Wiese"
    day.mkdir(parents=True)
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        (day / name).write_bytes(name.encode())
    lib = Library(tmp_path / "lib.sqlite")
    lib.add_root(tmp_path / "FPV")
    lib.close()

    app, window = _window(monkeypatch, tmp_path)
    QThreadPool.globalInstance().waitForDone(10000)
    app.processEvents()
    panel = window.library_panel
    group = panel._tree.topLevelItem(0)
    group.setSelected(True)
    assert len(panel.selected_entries()) == 3

    panel.review_toggled.emit([e.media_id for e in panel.selected_entries()], True)
    assert not any(e.is_new for e in window.library.entries())
    assert panel._tree.topLevelItem(0).text(2) == ""
    window.close()


def test_parse_tags():
    from fpvcut.ui.favorite_dialog import parse_tags

    assert parse_tags("Crash, flip ,, Gap, crash") == ["Crash", "flip", "Gap"]


def test_favorite_dialog_quick_tags():
    from fpvcut.ui.favorite_dialog import FavoriteDialog

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dialog = FavoriteDialog("00:01 – 00:03", ["Crash", "Flip"], tags=["crash"])
    assert dialog._buttons["crash"].isChecked()
    dialog._buttons["flip"].click()
    assert dialog.tags == ["crash", "Flip"]
    dialog._buttons["crash"].click()
    assert dialog.tags == ["Flip"]


def test_save_favorite_from_marks(monkeypatch, tmp_path):
    from PySide6.QtCore import QThreadPool

    from fpvcut.core.library import Library
    from fpvcut.ui import favorite_dialog

    day = tmp_path / "FPV" / "2026_08_28_Wiese"
    day.mkdir(parents=True)
    (day / "a.mp4").write_bytes(b"a")
    lib = Library(tmp_path / "lib.sqlite")
    lib.add_root(tmp_path / "FPV")
    lib.close()

    app, window = _window(monkeypatch, tmp_path)
    QThreadPool.globalInstance().waitForDone(10000)
    app.processEvents()
    window.open_entry(window.library.entries()[0])

    # In-Punkt bei 2 s, Speichern bei 5,5 s (ohne Out-Punkt): Ausschnitt 2–5,5 s.
    positions = iter([2.0, 5.5])
    monkeypatch.setattr(window.player, "position", lambda: next(positions))
    window.player.set_in()
    monkeypatch.setattr(favorite_dialog.FavoriteDialog, "exec", lambda self: favorite_dialog.QDialog.DialogCode.Accepted)
    monkeypatch.setattr(favorite_dialog.FavoriteDialog, "tags", property(lambda self: ["Flip"]))
    window.save_favorite()

    [clip] = window.library.clips_for(window.current_entry.media_id)
    assert (clip.in_ms, clip.out_ms, clip.tags) == (2000, 5500, ["Flip"])
    assert window.player.in_point is None  # Auswahl nach dem Speichern aufgehoben
    assert window.info_panel._clips.count() == 1
    video_item = window.library_panel._tree.topLevelItem(0).child(0)
    assert video_item.text(0) == "a.mp4"  # Name ohne Stern, der Stern ist das Icon links davon
    assert "1 Favoriten" in video_item.data(0, QtCore.Qt.ItemDataRole.AccessibleTextRole)
    window.play_clip(clip)  # ohne mpv: darf nicht abstürzen
    window.close()


def test_app_icon_renders_all_sizes():
    from fpvcut.ui.app_icon import SIZES, app_icon, render_icon

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    image = render_icon(64)
    assert image.pixelColor(32, 32).alpha() == 255  # Motiv sichtbar, nicht leer
    assert image.pixelColor(0, 0).alpha() == 0  # runde Ecken transparent
    sizes = {s.width() for s in app_icon().availableSizes()}
    assert sizes == set(SIZES)


def test_alt_f4_closes_window(monkeypatch, tmp_path):
    from fpvcut.ui import player

    monkeypatch.setattr(player, "load_mpv", lambda: (None, "test"))
    from fpvcut.ui.main_window import MainWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(db_path=tmp_path / "lib.sqlite")
    window.show()
    quit_action = next(a for a in window.actions() if "Alt+F4" in [k.toString() for k in a.shortcuts()])
    quit_action.trigger()
    app.processEvents()
    assert not window.isVisible()
