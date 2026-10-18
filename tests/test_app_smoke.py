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

    # Zwei Klicks mit mehr als 0,3 s Abstand: für Windows ein Doppelklick, für uns zwei Klicks.
    import time

    before = len(toggles)
    p._last_press = time.monotonic() - 0.4
    QtWidgets.QApplication.sendEvent(p._video, dbl)
    QTest.mouseRelease(p._video, left, pos=pos.toPoint())
    assert len(doubles) == 1
    assert len(toggles) == before + 1
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


def test_favorite_dialog_shows_all_tags_wrapped():
    from fpvcut.ui.favorite_dialog import FavoriteDialog

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tags = [f"Tag{i}" for i in range(30)] + ["crash", "Crash"]
    dialog = FavoriteDialog("00:01 – 00:03", tags)
    dialog.show()
    app.processEvents()
    buttons = list(dialog._buttons.values())
    assert len(buttons) == 31  # kein Limit mehr, Groß/klein-Dubletten nur einmal
    assert len({b.y() for b in buttons}) > 1  # umgebrochen
    assert all(b.width() < 100 for b in buttons)  # so breit wie der Text
    assert buttons[-1].geometry().bottom() <= dialog._quick.viewport().height()
    dialog.close()


class _FakeMpv(dict):
    """Steht für python-mpv: Frame-zurück bleibt beim ersten Versuch hängen."""

    def __init__(self):
        super().__init__({"hr-seek-demuxer-offset": 1.0})
        self.time_pos = 5.0
        self.commands = []

    def command(self, name):
        self.commands.append((name, self["hr-seek-demuxer-offset"]))
        if self["hr-seek-demuxer-offset"] > 1.0:
            self.time_pos -= 0.02


def test_stuck_frame_back_step_retries_with_larger_offset(monkeypatch, tmp_path):
    _app, window = _window(monkeypatch, tmp_path)
    p = window.player
    fake = _FakeMpv()
    p._player = fake
    p.step_frame(False)
    p._check_back_step(p._back_steps)
    assert [c[0] for c in fake.commands] == ["frame-back-step", "frame-back-step"]
    assert fake.commands[-1][1] == 5.0
    assert fake.time_pos < 5.0
    # Läuft es, wird nicht noch einmal nachgeschoben.
    p.step_frame(False)
    p._check_back_step(p._back_steps)
    assert len(fake.commands) == 3
    p._player = None
    window.close()


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
    assert "1 Ausschnitt" in video_item.data(0, QtCore.Qt.ItemDataRole.AccessibleTextRole)
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


def test_fresh_library_offers_restore_from_daily_backup(monkeypatch, tmp_path):
    from fpvcut.core.library import Library
    from fpvcut.core.scanner import scan_library
    from fpvcut.ui import player
    from fpvcut.ui.main_window import MainWindow
    from tests.test_scanner import fake_probe, write

    monkeypatch.setattr(player, "load_mpv", lambda: (None, "test"))
    monkeypatch.setattr(MainWindow, "rescan_library", lambda self: None)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    write(tmp_path / "FPV" / "2026-08-28_Wiese" / "a.mp4", b"aaa")
    old = Library(tmp_path / "alt" / "library.sqlite")
    old.add_root(tmp_path / "FPV")
    scan_library(old, fake_probe)
    old.add_clip(old.entries()[0].media_id, 0, 2000, ["Flip"])
    old.close()
    window = MainWindow(db_path=tmp_path / "alt" / "library.sqlite")  # Start legt die Tagessicherung an
    window.close()
    assert list((tmp_path / "alt" / "sicherungen").glob("favoriten_*.json"))

    # Neue, leere Datenbank im selben Ordner (z. B. nach Neuinstallation).
    (tmp_path / "alt" / "library.sqlite").unlink()
    for extra in (tmp_path / "alt").glob("library.sqlite-*"):
        extra.unlink()
    asked = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        lambda *a, **k: asked.append(a) or QtWidgets.QMessageBox.StandardButton.Yes)
    window = MainWindow(db_path=tmp_path / "alt" / "library.sqlite")
    app.processEvents()
    assert len(asked) == 1
    assert [c.tags for c in window.library.clips_for(None)] == [["Flip"]]
    window.close()


def test_project_save_and_dirty_prompt(monkeypatch, tmp_path):
    from fpvcut.timeline.model import TimelineClip
    from fpvcut.ui import main_window

    app, window = _window(monkeypatch, tmp_path)
    assert not window.project_modified()
    assert window.windowTitle().startswith("Unbenanntes Projekt –")

    window.timeline_panel.add_clips([TimelineClip(fingerprint="a", src_in=0, src_out=2)])
    assert window.project_modified()
    assert window.windowTitle().startswith("Unbenanntes Projekt* –")

    # Strg+S beim ersten Mal fragt nach dem Dateinamen, danach speichert es direkt.
    target = tmp_path / "Wiese.fpvcut.json"
    monkeypatch.setattr(main_window.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    assert window.save_project()
    assert target.exists() and not window.project_modified()
    assert window.windowTitle().startswith("Wiese –")

    window.timeline_panel.add_clips([TimelineClip(fingerprint="b", src_in=0, src_out=1)])
    assert window.windowTitle().startswith("Wiese* –")

    # Abbrechen behält alles, Nicht speichern verwirft, ohne die Datei anzufassen.
    buttons = main_window.QMessageBox.StandardButton
    monkeypatch.setattr(window, "_ask", lambda box: buttons.Cancel)
    window.new_project()
    assert len(window.timeline_panel.timeline.clips) == 2
    monkeypatch.setattr(window, "_ask", lambda box: buttons.Discard)
    window.new_project()
    assert not window.timeline_panel.timeline.clips and window.project_path is None
    assert len(main_window.Timeline.load(target).clips) == 1

    # Ohne Änderungen fragt Neu nicht nach.
    monkeypatch.setattr(window, "_ask", lambda box: pytest.fail("unnötige Nachfrage"))
    window.new_project()

    # Die gespeicherte Projektdatei bleibt nach einem Neustart bekannt.
    window.open_project(target)
    window.close()
    app, window = _window(monkeypatch, tmp_path)
    assert window.project_path == target and not window.project_modified()
    window.close()


def test_single_click_opens_library_video(monkeypatch, tmp_path):
    from PySide6.QtCore import QThreadPool

    from fpvcut.core.library import Library

    day = tmp_path / "FPV" / "2026_08_28_Wiese"
    day.mkdir(parents=True)
    (day / "a.mp4").write_bytes(b"a")
    lib = Library(tmp_path / "lib.sqlite")
    lib.add_root(tmp_path / "FPV")
    lib.close()

    app, window = _window(monkeypatch, tmp_path)
    QThreadPool.globalInstance().waitForDone(10000)
    app.processEvents()
    opened = []
    monkeypatch.setattr(window, "open_entry", lambda entry: opened.append(entry))
    tree = window.library_panel._tree
    tree.itemClicked.emit(tree.topLevelItem(0), 0)  # Flugtag-Zeile öffnet nichts
    tree.itemClicked.emit(tree.topLevelItem(0).child(0), 0)
    assert [e.path.name for e in opened] == ["a.mp4"]
    window.close()


def test_project_dialog_folder_and_recent_projects(monkeypatch, tmp_path):
    from fpvcut.core.library import Library
    from fpvcut.timeline.model import Timeline, TimelineClip
    from fpvcut.ui import main_window

    library_root = tmp_path / "FPV"
    library_root.mkdir()
    lib = Library(tmp_path / "lib.sqlite")
    lib.add_root(library_root)
    lib.close()
    monkeypatch.setattr(main_window.MainWindow, "rescan_library", lambda self: None)
    app, window = _window(monkeypatch, tmp_path)

    # Ohne frühere Wahl startet der Dialog im Bibliotheksordner, danach im zuletzt gewählten Ordner.
    seen = []
    elsewhere = tmp_path / "Projekte"
    elsewhere.mkdir()
    projects = []
    for name in ("eins", "zwei"):
        path = elsewhere / f"{name}.fpvcut.json"
        Timeline(clips=[TimelineClip(fingerprint=name, src_in=0, src_out=1)]).save(path)
        projects.append(path)

    def fake_open(_parent, _title, folder, _filter):
        seen.append(folder)
        return str(projects[len(seen) - 1]), ""

    monkeypatch.setattr(main_window.QFileDialog, "getOpenFileName", fake_open)
    window.open_project_dialog()
    window.open_project_dialog()
    assert seen == [str(library_root.resolve()), str(elsewhere)]
    assert window.recent_projects() == [str(projects[1]), str(projects[0])]

    window._fill_recent_menu()
    texts = [a.text() for a in window._recent_menu.actions() if not a.isSeparator()]
    assert texts == ["&1  zwei", "&2  eins", "Liste leeren"]
    window._recent_menu.actions()[1].trigger()
    assert window.project_path == projects[0]
    assert window.recent_projects()[0] == str(projects[0])
    window.close()

    # Ordner und Liste überstehen einen Neustart; eine verschwundene Datei fliegt aus der Liste.
    app, window = _window(monkeypatch, tmp_path)
    assert window._project_dir() == str(elsewhere)
    projects[1].unlink()
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda *a, **k: None)
    window.open_recent_project(projects[1])
    assert window.recent_projects() == [str(projects[0])]
    window.close()


def test_drag_on_clip_bar_marks_range_for_save_button(monkeypatch, tmp_path):
    from PySide6.QtCore import QEvent, QPointF, Qt, QThreadPool
    from PySide6.QtGui import QMouseEvent

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
    window.player._loaded = True  # ohne mpv: so tun, als liefe das Video
    bar = window.player._clip_bar
    bar.resize(220, bar.height())
    bar.set_inset(10)
    bar.set_duration(20.0)  # 200 Pixel Schiene für 20 s: 10 Pixel je Sekunde
    dialogs = []
    monkeypatch.setattr(favorite_dialog.FavoriteDialog, "exec",
                        lambda self: dialogs.append(self) or favorite_dialog.QDialog.DialogCode.Accepted)

    def mouse(kind, x, buttons):
        button = Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
        event = QMouseEvent(kind, QPointF(x, 5), QPointF(x, 5), button, buttons, Qt.KeyboardModifier.NoModifier)
        QtWidgets.QApplication.sendEvent(bar, event)

    left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    # Ein Klick springt nur und öffnet nichts.
    mouse(QEvent.Type.MouseButtonPress, 60, left)
    mouse(QEvent.Type.MouseButtonRelease, 61, none)
    assert not dialogs and window.player.in_point is None
    save = window.player._save_button
    assert not save.isEnabled()
    # Von rechts nach links ziehen: 8 s bis 3 s. Das markiert nur, der Dialog bleibt zu.
    mouse(QEvent.Type.MouseButtonPress, 90, left)
    mouse(QEvent.Type.MouseMove, 70, left)
    mouse(QEvent.Type.MouseMove, 40, left)
    mouse(QEvent.Type.MouseButtonRelease, 40, none)
    assert not dialogs and (window.player.in_point, window.player.out_point) == (3.0, 8.0)
    assert save.isEnabled()
    save.click()
    assert len(dialogs) == 1
    [clip] = window.library.clips_for(window.current_entry.media_id)
    assert (clip.in_ms, clip.out_ms) == (3000, 8000)
    assert not save.isEnabled()  # Auswahl nach dem Speichern aufgehoben
    # Nur ein In-Punkt ist noch kein Bereich.
    monkeypatch.setattr(window.player, "position", lambda: 4.0)
    window.player.set_in()
    assert not save.isEnabled()
    window.close()
