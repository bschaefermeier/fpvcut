import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from fpvcut.timeline.model import Timeline, TimelineClip  # noqa: E402
from fpvcut.ui.mime import MIME_CLIPS  # noqa: E402
from tests.test_favorites_browser import make_lib  # noqa: E402


def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def clips():
    return [TimelineClip(n, 0, 5, 10, f"{n}.mp4", path=Path(f"/v/{n}.mp4")) for n in "abc"]


def panel_with_clips():
    from fpvcut.ui.timeline_panel import TimelinePanel

    app()
    panel = TimelinePanel()
    panel.resize(900, 160)
    panel.show()
    panel.add_clips(clips())
    return panel


def center(view, index):
    return view.clip_rects()[index].center().toPoint()


def test_drag_clip_to_new_position_and_undo():
    panel = panel_with_clips()
    view = panel.view
    target = QPoint(int(view.clip_rects()[2].right() - 5), center(view, 2).y())
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=center(view, 0))
    QTest.mouseMove(view, center(view, 1))
    QTest.mouseMove(view, target)
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=target)
    assert [c.fingerprint for c in panel.timeline.clips] == ["b", "c", "a"]
    assert view.selected == 2
    assert panel.undo()
    assert [c.fingerprint for c in panel.timeline.clips] == ["a", "b", "c"]
    assert panel.redo()
    assert [c.fingerprint for c in panel.timeline.clips] == ["b", "c", "a"]


def test_trim_end_by_dragging_edge():
    panel = panel_with_clips()
    view = panel.view
    rect = view.clip_rects()[0]
    edge = QPoint(int(rect.right() - 1), int(rect.center().y()))
    assert view.hit(QPointF(edge))[2] == "end"
    shorter = edge - QPoint(int(2 * view.pps), 0)  # 2 s nach links
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=edge)
    QTest.mouseMove(view, shorter)
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=shorter)
    assert panel.timeline.clips[0].src_out == pytest.approx(3, abs=0.1)
    assert panel.timeline.duration == pytest.approx(13, abs=0.1)
    assert panel.undo() and panel.timeline.clips[0].src_out == 5


def test_split_delete_and_scrub():
    panel = panel_with_clips()
    view = panel.view
    seeks = []
    panel.seek_requested.connect(seeks.append)
    ruler = QPoint(int(view._x(7.5)), 5)
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=ruler)
    assert view.playhead == pytest.approx(7.5, abs=0.05) and seeks
    assert panel.split_at_playhead()
    assert [(c.fingerprint, c.src_in, c.src_out) for c in panel.timeline.clips[1:3]] == [
        ("b", 0, pytest.approx(2.5, abs=0.05)), ("b", pytest.approx(2.5, abs=0.05), 5)
    ]
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Delete)  # löscht das zweite Teilstück (ausgewählt)
    assert [c.fingerprint for c in panel.timeline.clips] == ["a", "b", "c"]
    assert panel.timeline.duration == pytest.approx(12.5, abs=0.05)


def test_drop_favorites_emits_ids_and_position():
    panel = panel_with_clips()
    view = panel.view
    dropped = []
    panel.clips_dropped.connect(lambda ids, index: dropped.append((ids, index)))
    mime = QMimeData()
    mime.setData(MIME_CLIPS, json.dumps([7, 9]).encode())
    pos = QPointF(view._x(6), view.clip_rects()[0].center().y())  # in der ersten Hälfte von Clip b
    event = QDropEvent(pos, Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    view.dropEvent(event)
    assert dropped == [([7, 9], 1)]


def _window(monkeypatch, tmp_path):
    from fpvcut.ui import player
    from fpvcut.ui.main_window import MainWindow

    make_lib(tmp_path).close()
    monkeypatch.setattr(player, "load_mpv", lambda: (None, "test"))
    monkeypatch.setattr(MainWindow, "rescan_library", lambda self: None)
    app()
    return MainWindow(db_path=tmp_path / "lib.sqlite")


def test_favorites_go_to_timeline_and_survive_restart(monkeypatch, tmp_path):
    window = _window(monkeypatch, tmp_path)
    window.side_tabs.setCurrentWidget(window.favorites_panel)
    tree = window.favorites_panel._tree
    tree.topLevelItem(0).setSelected(True)
    tree.topLevelItem(2).setSelected(True)
    window.add_selection_to_timeline()  # Taste E
    timeline = window.timeline_panel.timeline
    assert [c.label for c in timeline.clips] == ["neu.mp4", "alt.mp4"]
    assert timeline.clips[0].path is not None
    assert (timeline.clips[1].src_in, timeline.clips[1].src_out) == (0.2, 0.8)
    window.close()

    # Neues Fenster: Timeline wird aus der automatischen Sicherung geladen, Pfade neu aufgelöst.
    from fpvcut.ui.main_window import MainWindow

    window = MainWindow(db_path=tmp_path / "lib.sqlite")
    restored = window.timeline_panel.timeline
    assert [c.label for c in restored.clips] == ["neu.mp4", "alt.mp4"]
    assert all(c.path is not None for c in restored.clips)
    window.close()


def test_marked_range_goes_to_timeline(monkeypatch, tmp_path):
    window = _window(monkeypatch, tmp_path)
    entry = next(e for e in window.library.entries() if e.path.name == "alt.mp4")
    window.open_entry(entry)
    positions = iter([0.25, 0.75, 1.0])
    monkeypatch.setattr(window.player, "position", lambda: next(positions))
    window.player.set_in()
    window.player.set_out()
    window.add_selection_to_timeline()
    [clip] = window.timeline_panel.timeline.clips
    assert (clip.src_in, clip.src_out, clip.label) == (0.25, 0.75, "alt.mp4")
    assert not window.player.has_marks()
    window.close()


def test_play_timeline_reports_missing_files(monkeypatch, tmp_path):
    window = _window(monkeypatch, tmp_path)
    window.play_timeline()
    assert "leer" in window.statusBar().currentMessage()
    window.timeline_panel.add_clips([TimelineClip("weg", 0, 1, 2, "weg.mp4")])
    window.play_timeline()
    assert "weg.mp4" in window.statusBar().currentMessage()
    assert not window.timeline_mode
    window.timeline_panel.set_timeline(Timeline(clips()))
    window.play_timeline(0)
    assert window.timeline_mode and window.current_entry is None
    window.close()


def test_edge_between_clips_belongs_to_selected_clip():
    panel = panel_with_clips()
    view = panel.view
    boundary = QPointF(view.clip_rects()[0].right(), view.clip_rects()[0].center().y())
    left, right = boundary - QPointF(5, 0), boundary + QPointF(5, 0)
    view.select(0)
    assert {view.hit(p)[1:] for p in (left, boundary, right)} == {(0, "end")}
    view.select(1)  # auch knapp links der Grenze gehört die Kante dem ausgewählten rechten Clip
    assert {view.hit(p)[1:] for p in (left, boundary, right)} == {(1, "start")}
    view.select(None)
    assert view.hit(left)[1:] == (0, "end") and view.hit(right)[1:] == (1, "start")


def test_trim_beyond_favorite_is_painted(monkeypatch):
    panel = panel_with_clips()
    clip = panel.timeline.clips[0]
    clip.fav_in, clip.fav_out = 1.0, 4.0  # Favorit war 1–4 s, Clip ist auf 0–5 s verlängert
    painted = []
    original = panel.view._paint_extensions

    def spy(painter, rect, c):
        painted.append(c.fingerprint)
        original(painter, rect, c)

    monkeypatch.setattr(panel.view, "_paint_extensions", spy)
    panel.view.grab()
    assert painted[0] == "a"


def test_library_videos_go_to_timeline(monkeypatch, tmp_path):
    from fpvcut.ui.mime import MIME_MEDIA

    window = _window(monkeypatch, tmp_path)
    tree = window.library_panel._tree
    group = tree.topLevelItem(0)  # ein ganzer Flugtag
    mime = tree.mimeData([group])
    ids = json.loads(bytes(mime.data(MIME_MEDIA)).decode())
    window.add_videos_to_timeline(ids)
    [clip] = window.timeline_panel.timeline.clips
    assert (clip.src_in, clip.src_out, clip.fav_in) == (0.0, 1.0, None)  # ganzes Video
    group.child(0).setSelected(True)
    window.side_tabs.setCurrentWidget(window.library_panel)
    window.add_selection_to_timeline()  # Taste E in der Bibliothek
    assert len(window.timeline_panel.timeline.clips) == 2
    window.close()


def test_play_without_video_and_click_in_timeline_start_preview(monkeypatch, tmp_path):
    window = _window(monkeypatch, tmp_path)
    window.timeline_panel.set_timeline(Timeline(clips()))
    calls = []
    monkeypatch.setattr(window.player, "open_timeline", lambda edl, lavfi, start=0, paused=False: calls.append((start, paused)))
    window.player.toggle_pause()  # Leertaste/Play, ohne dass ein Video geladen ist
    assert window.timeline_mode and calls == [(0.0, False)]
    window.timeline_mode = False
    window._on_timeline_seek(7.0)  # Klick ins Lineal
    assert window.timeline_mode and calls[-1] == (7.0, True)
    window.close()
