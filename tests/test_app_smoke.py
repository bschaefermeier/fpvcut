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
