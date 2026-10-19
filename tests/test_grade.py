import shutil
import subprocess
from pathlib import Path

import pytest

from fpvcut.render.command import build_command, build_filter
from fpvcut.timeline.edl import build_edl, build_vf
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
    assert grade_filters(Grade(sharpness=-0.5)) == ["unsharp=lx=5:ly=5:la=-0.500"]
    tone = grade_filters(Grade(shadows=0.5, vibrance=0.3), enable="gte(t,1)")
    assert tone[0] == "vibrance=intensity=0.300:enable='gte(t,1)'"
    assert tone[1].startswith("lutyuv=y='clip(val+") and tone[1].endswith(":enable='gte(t,1)'")
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
    assert build_vf(tl) == ("lavfi=[scale=w=-2:h='min(ih,1080)':flags=bilinear,"
                            "eq=brightness=0.000:contrast=1.000:saturation=0.000:gamma=1.000"
                            ":enable='gte(t,2.000)*lt(t,5.000)']")
    assert build_vf(Timeline(clips[:1])) == ""
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
        vf = build_vf(tl)
        player = mpv.MPV(vo="null", ao="null", o=str(out), ovc="ffv1")
        try:
            player.loadfile(build_edl(tl), start=str(start), vf=f"%{len(vf.encode())}%{vf}")
            player.wait_for_playback(timeout=30)
        finally:
            player.terminate()
        for t, colorful in checks.items():
            assert (_chroma(out, t) > 50) == colorful, (start, t)


def test_preview_with_grade_copies_hw_frames_for_filters():
    """Hardware-dekodierte Bilder liegen im Grafikspeicher; die Farbfilter brauchen sie im RAM."""
    from fpvcut.ui.player import PlayerWidget

    calls = []

    class FakeMpv:
        pause = False

        def loadfile(self, url, **options):
            calls.append(options)

    player = PlayerWidget.__new__(PlayerWidget)
    player._player = FakeMpv()
    player.clear_marks = player.set_clips = lambda *a: None
    player.open_timeline("edl://x", False, "lavfi=[eq=saturation=0]")
    player.open_timeline("edl://x", False, "")
    assert calls[0]["hwdec"] == "auto-copy-safe" and "hwdec" not in calls[1]


@needs_ffmpeg
def test_render_applies_sharpness(tmp_path):
    def edges(path: Path) -> float:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(path), "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
        return sum(abs(a - b) for a, b in zip(raw, raw[1:])) / len(raw)

    src = _graded_timeline(tmp_path).clips[0].path
    results = {}
    for amount in (-1.0, 0.0, 1.5):
        tl = Timeline([TimelineClip("a", 0, 2, 4, path=src, has_audio=False, grade={"sharpness": amount})])
        s = settings(tmp_path, output=tmp_path / f"scharf_{amount}.mp4", width=160, height=90, fps=25)
        subprocess.run(build_command("ffmpeg", tl, s), check=True, capture_output=True)
        results[amount] = edges(s.output)
    assert results[-1.0] < results[0.0] < results[1.5]


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
                        lambda edl, lavfi, vf, start=0, paused=False: previews.append((vf, start, paused)))
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
    # Automatik: misst den Clip (hier ersetzt) und setzt die Regler in einem Rückgängig-Schritt.
    from fpvcut.timeline.auto_grade import Stats
    from fpvcut.ui import grade_panel

    monkeypatch.setattr(grade_panel, "find_tool", lambda name: "ffmpeg")
    monkeypatch.setattr(grade_panel, "measure",
                        lambda ffmpeg, path, a, b, lut: Stats(0.25, 0.4, 0.6, 0.0, -5, 5, 10))
    panel.set_lut("/luts/dlog.cube")
    panel.auto_grade()
    auto = Grade.from_dict(window.timeline_panel.timeline.clips[1].grade)
    assert auto.contrast > 1.3 and auto.lut == "/luts/dlog.cube"
    assert panel.sliders["contrast"].value() == round(auto.contrast * 1000)
    window.timeline_panel.undo()
    assert Grade.from_dict(window.timeline_panel.timeline.clips[1].grade).contrast == 1.0
    window._on_escape()  # Esc hebt die Auswahl in der Timeline auf
    assert window.timeline_panel.view.selected is None and not panel.sliders["contrast"].isEnabled()
    window.close()


@needs_ffmpeg
def test_tone_curve_lifts_shadows_and_stays_monotonic():
    ramp = "gradients=s=256x16:c0=black:c1=white:x0=0:y0=0:x1=255:y1=0:nb_colors=2,format=yuv420p10le"
    for grade, darker_mid in ((Grade(shadows=1), False), (Grade(highlights=-1), True)):
        vf = ",".join(grade_filters(grade)) + ",format=gray"
        out = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", ramp, "-frames:v", "1", "-vf", vf,
                              "-f", "rawvideo", "-"], capture_output=True, check=True).stdout[:256]
        plain = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", ramp, "-frames:v", "1", "-vf",
                                "format=gray", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout[:256]
        assert all(b >= a - 2 for a, b in zip(out, out[1:]))  # keine Tonwertumkehr
        assert (out[85] < plain[85] - 10 if darker_mid else out[85] > plain[85] + 10)
        assert out[0] == plain[0]  # Schwarz bleibt schwarz


def test_auto_grade_suggestion():
    from fpvcut.timeline.auto_grade import Stats, suggest

    flat_warm = Stats(low=0.25, median=0.42, high=0.6, clipped=0.0, u=-8, v=8, chroma=10)
    grade = suggest(flat_warm, Grade(lut="x.cube", sharpness=0.4, saturation=0.3))
    assert grade.lut == "x.cube" and grade.sharpness == 0.4  # bleiben
    assert grade.saturation == 1.0  # wird neu gesetzt
    assert grade.contrast > 1.3 and grade.temperature > 6500 and grade.vibrance > 0.3
    good = suggest(Stats(low=0.08, median=0.49, high=0.9, clipped=0.0, u=0, v=0, chroma=30))
    assert abs(good.contrast - 1) < 0.05 and abs(good.brightness) < 0.02 and abs(good.gamma - 1) < 0.02
    assert good.temperature == 6500 and good.vibrance == 0 and good.shadows == good.highlights == 0
    bright = suggest(Stats(low=0.2, median=0.8, high=1.0, clipped=0.2, u=0, v=0, chroma=30))
    assert bright.highlights < 0 and bright.brightness < 0


@needs_ffmpeg
def test_auto_grade_measures_clip(tmp_path):
    from fpvcut.timeline.auto_grade import measure, suggest

    src = tmp_path / "flau.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=2",
                    "-vf", "eq=contrast=0.6:saturation=0.2,colortemperature=temperature=4000", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(src)], check=True)
    stats = measure("ffmpeg", src, 0, 2)
    assert stats.high - stats.low < 0.5 and stats.v - stats.u > 3  # flau und warm
    grade = suggest(stats)
    assert grade.contrast > 1.3 and grade.temperature > 6500
