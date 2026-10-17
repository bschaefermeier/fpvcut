import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


def test_main_window_starts_without_libmpv(monkeypatch):
    """Das Fenster muss auch ohne libmpv starten und einen Hinweis zeigen."""
    from fpvcut.ui import player

    monkeypatch.setattr(player, "load_mpv", lambda: (None, "test"))
    from fpvcut.ui.main_window import MainWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()
    assert not window.player.available
    assert "libmpv" in window.player._message.text()
    window.close()


def test_fullscreen_toggle_keeps_shortcuts(monkeypatch):
    from fpvcut.ui import player

    monkeypatch.setattr(player, "load_mpv", lambda: (None, "test"))
    from fpvcut.ui.main_window import MainWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow()
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
