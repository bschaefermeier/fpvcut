"""KI-Reinigung: Render-Eingänge, Vorschau-EDL, Schalter in der Farbkorrektur und (mit PyTorch,
Grafikkarte und Checkpoints) Lehrer/Schüler im Render und live in der Vorschau."""

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from fpvcut import restore
from fpvcut.render.command import RenderSettings, SourceFormat, build_command, clip_inputs
from fpvcut.timeline.edl import build_edl
from fpvcut.timeline.grade import Grade, grade_filters
from fpvcut.timeline.model import MusicTrack, Timeline, TimelineClip

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg fehlt")


def _cuda() -> bool:
    if not restore.torch_installed():
        return False
    import torch

    return torch.cuda.is_available()


needs_models = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or not _cuda() or restore.problem("student") or restore.problem("teacher"),
    reason="PyTorch mit CUDA oder Checkpoints fehlen",
)


def test_restore_switch_is_part_of_grade_but_no_filter():
    grade = Grade(restore=True, remove_osd=True)
    assert not grade.is_neutral and grade_filters(grade) == []
    assert Grade.from_dict(grade.to_dict()) == grade


def test_restored_clip_takes_picture_from_file_and_sound_from_original(tmp_path):
    tl = Timeline([TimelineClip("a", 1, 3, path=Path("a.mp4")),
                   TimelineClip("b", 5, 6, path=Path("b.mp4")),
                   TimelineClip("c", 0, 2, has_audio=False, path=Path("c.mp4"))],
                  music=MusicTrack("m.mp3", duration=60))
    restored = {1: tmp_path / "b_ki.mp4", 2: tmp_path / "c_ki.mp4"}
    args, streams = clip_inputs(tl, restored)
    inputs = [args[i + 1] for i, a in enumerate(args) if a == "-i"]
    assert inputs == ["a.mp4", str(restored[1]), "b.mp4", str(restored[2])]
    assert streams == [(0, 0), (1, 2), (3, 3)]  # Clip c ohne Ton: kein zweiter Eingang
    cmd = build_command("ffmpeg", tl, RenderSettings(tmp_path / "o.mp4", 1280, 720, 50, "libx264", 23), restored)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "[1:v]" in graph and "[2:a]" in graph and "[4:a]aresample" in graph  # Musik ist Eingang 4
    assert cmd[cmd.index(str(restored[1])) - 3:cmd.index(str(restored[1]))] == ["-t", "1.000", "-i"]


def test_preview_edl_uses_restored_source_for_clip():
    tl = Timeline([TimelineClip("a", 1, 3, path=Path("a.mp4")), TimelineClip("b", 5, 6, path=Path("b.mp4"))])
    edl = build_edl(tl, sources={1: "fpvki://123"})
    assert edl.endswith("%5%a.mp4,1.000,2.000;%11%fpvki://123,0.000,1.000")


def test_grade_panel_switches_restore_and_reset_keeps_it(tmp_path, monkeypatch):
    from fpvcut.ui.main_window import MainWindow

    monkeypatch.setattr(restore, "problem", lambda kind="student": None)
    window = MainWindow(db_path=tmp_path / "lib.sqlite")
    monkeypatch.setattr(window.player, "open_timeline", lambda *a, **kw: None)
    clips = [TimelineClip(n, 0, 4, 10, f"{n}.mp4", path=Path(f"/v/{n}.mp4")) for n in "ab"]
    window.timeline_panel.set_timeline(Timeline(clips))
    window.timeline_panel.view.select(1)
    panel = window.grade_panel
    assert panel._restore.isEnabled() and not panel._remove_osd.isEnabled()
    panel._restore.setChecked(True)
    panel._remove_osd.setChecked(True)
    assert window.timeline_panel.timeline.clips[1].grade == Grade(restore=True, remove_osd=True).to_dict()
    assert clips[0].grade is None
    panel.sliders["saturation"].setValue(500)
    panel.reset()
    assert Grade.from_dict(window.timeline_panel.timeline.clips[1].grade) == Grade(restore=True, remove_osd=True)
    window.timeline_panel.undo()
    assert Grade.from_dict(window.timeline_panel.timeline.clips[1].grade).saturation == 0.5
    window.close()


@pytest.fixture
def analog_clip(tmp_path):
    """Kurzes Video im Format der BoxPro+ (1280 × 720, 60 fps, Bild ab x = 40) mit Ton."""
    src = tmp_path / "hdz.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1200x720:rate=60:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-vf", "pad=1280:720:40:0,noise=alls=40:allf=t",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(src)], check=True)
    return src


@needs_models
@pytest.mark.parametrize("stride", [1, 2, 3, 4, 5])
def test_teacher_delivers_every_frame_once_for_each_stride(analog_clip, stride):
    from fpvcut.restore.engine import ClipSpec, Geometry, restored

    spec = ClipSpec(analog_clip, 0.5, 0.3, 60.0, Geometry.for_source(1280, 720))
    frames = list(restored("ffmpeg", spec, restore.models(), "teacher", stride))
    assert [i for i, _ in frames] == list(range(18))
    assert frames[0][1].shape == (3, 352, 592)
    restore.models().release("teacher")


def _probe(path: Path, entries: str) -> str:
    return subprocess.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True, check=True).stdout.strip()


@needs_models
def test_render_dialog_cleans_up_marked_clips_first(tmp_path, monkeypatch, analog_clip):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from fpvcut.ui import render_dialog
    from fpvcut.ui.render_dialog import RenderDialog

    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(render_dialog, "app_settings", lambda: QSettings(ini, QSettings.Format.IniFormat))
    clean = Grade(restore=True).to_dict()
    tl = Timeline([TimelineClip("a", 0.5, 1.5, path=analog_clip, grade=clean),
                   TimelineClip("a", 2.0, 2.5, path=analog_clip)])
    fmt = SourceFormat(1280, 720, 60.0)
    dialog = RenderDialog(tl, fmt, Path(shutil.which("ffmpeg")), None, formats=lambda t: [fmt] * len(t.clips))
    assert dialog._teacher.isEnabled() and "1 Clip" in dialog._restore_info.text()
    dialog._teacher.setChecked(True)
    dialog._stride.setValue(5)
    dialog._path.setText(str(tmp_path / "out.mp4"))
    assert dialog.start()
    assert dialog.wait(120_000)
    QApplication.processEvents()
    out = tmp_path / "out.mp4"
    assert dialog._status.text().startswith("Fertig"), dialog._status.text()
    assert float(_probe(out, "format=duration")) == pytest.approx(1.5, abs=0.1)
    assert _probe(out, "stream=codec_type").split() == ["video", "audio"]
    assert dialog._temp is None  # Zwischendateien sind weg


@needs_models
def test_live_preview_plays_restored_clip_in_real_time(analog_clip):
    import locale

    from fpvcut.restore.engine import ClipSpec, Geometry
    from fpvcut.restore.stream import PreviewService
    from fpvcut.ui.player import load_mpv

    mpv, error = load_mpv()
    if mpv is None:
        pytest.skip(error)
    locale.setlocale(locale.LC_NUMERIC, "C")
    player = mpv.MPV(vo="null", ao="null", keep_open="yes")
    try:
        service = PreviewService("ffmpeg", restore.models())
        service.register(mpv, player)
        tl = Timeline([TimelineClip("a", 0.0, 1.0, path=analog_clip), TimelineClip("a", 0.5, 2.5, path=analog_clip)])
        url = service.url(ClipSpec(analog_clip, 0.5, 2.0, 60.0, Geometry.for_source(1280, 720), True))
        player.loadfile(build_edl(tl, sources={1: url}), start="0.8", aid="no", load_unsafe_playlists="yes")
        deadline = time.monotonic() + 15
        while (player.time_pos or 0) < 2.5 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (player.time_pos or 0) >= 2.5, service.last_error
        assert player.video_params["w"] == 640 and player.frame_drop_count == 0
        assert service.last_error is None
    finally:
        player.terminate()
