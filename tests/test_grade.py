import shutil
import subprocess
from pathlib import Path

import pytest

from fpvcut.render.command import build_command, build_filter
from fpvcut.timeline.edl import build_edl, build_lavfi
from fpvcut.timeline.grade import Grade, grade_filters
from fpvcut.timeline.model import Timeline, TimelineClip
from tests.test_render import settings

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg fehlt")


def test_grade_filters_and_storage(tmp_path):
    assert grade_filters(None) == [] and grade_filters(Grade()) == []
    assert Grade().to_dict() is None
    grade = Grade(brightness=0.05, saturation=1.3, temperature=5200, lut="C:\\LUTs\\D-Log.cube")
    assert grade_filters(grade) == [
        "lut3d=file='C\\:/LUTs/D-Log.cube':interp=tetrahedral",
        "colortemperature=temperature=5200:pl=1",
        "eq=brightness=0.050:contrast=1.000:saturation=1.300:gamma=1.000",
    ]
    assert grade_filters(grade.to_dict(), enable="gte(t,1)")[2].endswith(":enable='gte(t,1)'")
    assert Grade.from_dict({**grade.to_dict(), "unbekannt": 1}) == grade  # Felder späterer Versionen stören nicht
    # Die Korrektur wird mit der Timeline gespeichert und kopiert (Rückgängig).
    tl = Timeline([TimelineClip("a", 0, 2, 4, "a.mp4", grade=grade.to_dict())])
    tl.save(tmp_path / "t.json")
    assert Timeline.load(tmp_path / "t.json").clips[0].grade == grade.to_dict()
    assert tl.copy().clips[0].grade == grade.to_dict()


def test_preview_and_render_filters_use_grade():
    clips = [TimelineClip("a", 0, 2, 4, path=Path("/v/a.mp4")),
             TimelineClip("b", 1, 4, 4, path=Path("/v/b.mp4"), grade={"saturation": 0.0})]
    tl = Timeline(clips)
    lavfi = build_lavfi(tl)
    assert lavfi.startswith("[vid1]eq=brightness=0.000:contrast=1.000:saturation=0.000:gamma=1.000"
                            ":enable='gte(t,2.000)*lt(t,5.000)'[vo]")
    f = build_filter(tl, settings(Path("/tmp")))
    assert "[0:v]scale=" in f and "[1:v]eq=brightness=0.000:contrast=1.000:saturation=0.000:gamma=1.000,scale=" in f


def _chroma(path: Path, t: float) -> float:
    """Mittlere Farbigkeit eines Bildes: 0 = grau."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "yuv444p", "-"], capture_output=True, check=True).stdout
    n = len(raw) // 3
    return (sum(abs(b - 128) for b in raw[n:2 * n]) + sum(abs(b - 128) for b in raw[2 * n:])) / n


def _graded_timeline(tmp_path):
    src = tmp_path / "bunt.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=25:duration=4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True)
    return Timeline([TimelineClip("a", 0, 2, 4, path=src, has_audio=False),
                     TimelineClip("a", 2, 4, 4, path=src, has_audio=False, grade={"saturation": 0.0})])


@needs_ffmpeg
def test_render_applies_grade_per_clip(tmp_path):
    tl = _graded_timeline(tmp_path)
    s = settings(tmp_path, width=160, height=90, fps=25)
    subprocess.run(build_command("ffmpeg", tl, s), check=True, capture_output=True)
    assert _chroma(s.output, 1.0) > 50  # erster Clip bunt
    assert _chroma(s.output, 3.0) < 5  # zweiter Clip grau


@needs_ffmpeg
def test_preview_applies_grade_only_in_its_clip(tmp_path):
    """mpv rendert die Vorschau in eine Datei; auch beim Start mitten in der Timeline."""
    from fpvcut.ui.player import load_mpv

    mpv, _error = load_mpv()
    if mpv is None:
        pytest.skip("libmpv fehlt")
    tl = _graded_timeline(tmp_path)
    for start, checks in ((0.0, {1.0: True, 3.0: False}), (1.5, {0.2: True, 1.5: False})):
        out = tmp_path / f"vorschau_{start}.mkv"
        lavfi = build_lavfi(tl, start)
        player = mpv.MPV(vo="null", ao="null", o=str(out), ovc="ffv1")
        try:
            player.loadfile(build_edl(tl), start=str(start), lavfi_complex=f"%{len(lavfi.encode())}%{lavfi}")
            player.wait_for_playback(timeout=30)
        finally:
            player.terminate()
        for t, colorful in checks.items():
            assert (_chroma(out, t) > 50) == colorful, (start, t)


def test_grade_panel_edits_selected_clip_with_undo(monkeypatch, tmp_path):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from fpvcut.ui import player
    from fpvcut.ui.main_window import MainWindow

    monkeypatch.setattr(player, "load_mpv", lambda: (None, "test"))
    monkeypatch.setattr(MainWindow, "rescan_library", lambda self: None)
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(db_path=tmp_path / "lib.sqlite")
    previews = []
    monkeypatch.setattr(window.player, "open_timeline",
                        lambda edl, lavfi, start=0, paused=False: previews.append((lavfi, start, paused)))
    clips = [TimelineClip(n, 0, 4, 10, f"{n}.mp4", path=Path(f"/v/{n}.mp4")) for n in "abc"]
    window.timeline_panel.set_timeline(Timeline(clips))
    panel = window.grade_panel
    assert not panel.sliders["saturation"].isEnabled()  # nichts ausgewählt

    window.timeline_panel.view.select(1)
    assert panel.sliders["saturation"].isEnabled()
    panel.sliders["saturation"].setValue(500)  # wie per Tastatur/Mausrad
    assert clips[1].grade["saturation"] == 0.5 and clips[0].grade is None
    # Vorschau zeigt sofort den korrigierten Clip, Abspielkopf steht darin.
    assert previews and 4 <= previews[-1][1] < 8 and previews[-1][2] is True
    assert "saturation=0.500" in previews[-1][0]

    panel.sliders["temperature"].setValue(5000)
    panel.set_lut("/luts/dlog.cube")
    assert window.timeline_panel.timeline.clips[1].grade["lut"] == "/luts/dlog.cube"
    panel.apply_to_all()
    assert all(c.grade["temperature"] == 5000 for c in window.timeline_panel.timeline.clips)
    window.timeline_panel.undo()  # "auf alle" zurück
    assert window.timeline_panel.timeline.clips[0].grade is None
    window.timeline_panel.view.select(1)
    panel.refresh()
    assert panel.sliders["temperature"].value() == 5000
    # Doppelklick auf Regler oder Wert setzt nur diesen Wert zurück.
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    slider = panel.sliders["temperature"]
    QTest.mouseDClick(slider, Qt.MouseButton.LeftButton, pos=slider.rect().center())
    assert slider.value() == 6500
    assert Grade.from_dict(window.timeline_panel.timeline.clips[1].grade).temperature == 6500
    panel.sliders["contrast"].setValue(1200)
    QTest.mouseDClick(panel._labels["contrast"], Qt.MouseButton.LeftButton)
    assert panel.sliders["contrast"].value() == 1000
    assert window.timeline_panel.timeline.clips[1].grade["lut"] == "/luts/dlog.cube"  # Rest bleibt
    panel.reset()
    assert window.timeline_panel.timeline.clips[1].grade is None
    assert panel.sliders["saturation"].value() == 1000
    window.close()
