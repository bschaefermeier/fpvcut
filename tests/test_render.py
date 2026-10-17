import array
import cmath
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from fpvcut.render.command import (
    RenderSettings, SourceFormat, build_command, build_filter, encoder_args, parse_progress, source_format,
)
from fpvcut.timeline.model import MusicTrack, Timeline, TimelineClip

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg fehlt")


def settings(tmp_path, **kw):
    base = dict(output=tmp_path / "out.mp4", width=1280, height=720, fps=50, encoder="libx264", quality=30)
    return RenderSettings(**{**base, **kw})


def test_source_format_weighted_by_length():
    tl = Timeline([TimelineClip("a", 0, 2), TimelineClip("b", 0, 5), TimelineClip("c", 0, 1)])
    fmts = [SourceFormat(1280, 720, 50), SourceFormat(1920, 1080, 30), None]
    assert source_format(tl, fmts) == SourceFormat(1920, 1080, 30)
    assert source_format(tl, [None, None, None]) == SourceFormat(1280, 720, 50)


def test_encoder_args():
    assert encoder_args(RenderSettings(Path("x"), 2, 2, 50, "hevc_nvenc", 18, ten_bit=True)) == [
        "-c:v", "hevc_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "18", "-b:v", "0",
        "-spatial-aq", "1", "-profile:v", "main10", "-tag:v", "hvc1",
    ]
    assert encoder_args(RenderSettings(Path("x"), 2, 2, 50, "libx264", 23)) == [
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
    ]


def test_filter_fills_silence_and_mixes_music(tmp_path):
    tl = Timeline([TimelineClip("a", 1, 3, path=Path("a")), TimelineClip("b", 0, 2, has_audio=False, path=Path("b"))])
    f = build_filter(tl, settings(tmp_path, width=1281))
    assert "scale=1280:720" in f  # ungerade Breite wird gerade gemacht
    assert "anullsrc=r=48000:cl=stereo,atrim=duration=2.000[a1]" in f
    assert f.endswith("[acat]volume=1.00[aout]")
    tl.music = MusicTrack("m.mp3", duration=60, fade_out=1)
    f = build_filter(tl, settings(tmp_path))
    assert "[2:a]aresample=48000" in f and "afade=t=out:st=3.000:d=1.00[amusic]" in f
    assert f.endswith("amix=inputs=2:normalize=0:duration=first[aout]")
    cmd = build_command("ffmpeg", tl, settings(tmp_path))
    assert cmd[cmd.index("-i") - 4:cmd.index("-i") + 2] == ["-ss", "1.000", "-t", "2.000", "-i", "a"]
    assert cmd[-1] == str(tmp_path / "out.mp4")


def test_parse_progress():
    assert parse_progress("out_time_us=2500000\n") == 2.5
    assert parse_progress("out_time_ms=-1") == 0
    assert parse_progress("progress=continue") is None


def _tone_level(path, start, freq):
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-ss", str(start), "-t", "0.1", "-i", str(path),
         "-ac", "1", "-ar", "48000", "-f", "s16le", "-"], capture_output=True, check=True,
    ).stdout
    x = array.array("h", raw)
    return abs(sum(v * cmath.exp(-2j * math.pi * freq * i / 48000) for i, v in enumerate(x))) / max(len(x), 1)


@needs_ffmpeg
def test_render_mixed_formats_silent_clip_and_music(tmp_path):
    run = ["ffmpeg", "-loglevel", "error", "-y"]
    a, b, m = tmp_path / "a.mp4", tmp_path / "b, 1080.mp4", tmp_path / "m.mp3"
    subprocess.run([*run, "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=50:duration=4",
                    "-f", "lavfi", "-i", "sine=f=440:d=4", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", str(a)], check=True)
    subprocess.run([*run, "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=3",
                    "-c:v", "libx264", "-preset", "ultrafast", str(b)], check=True)
    subprocess.run([*run, "-f", "lavfi", "-i", "sine=f=880:d=20", str(m)], check=True)
    tl = Timeline([
        TimelineClip("a", 0.5, 2.0, path=a),
        TimelineClip("b", 0.0, 1.5, has_audio=False, path=b),
        TimelineClip("a", 2.0, 3.0, path=a),
    ])
    tl.music = MusicTrack(str(m), duration=20, volume=0.5, fade_out=0)
    s = settings(tmp_path, quality=35)
    result = subprocess.run(build_command("ffmpeg", tl, s), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert any(parse_progress(line) for line in result.stdout.splitlines())

    info = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(s.output)],
        capture_output=True, text=True, check=True).stdout)
    video = next(st for st in info["streams"] if st["codec_type"] == "video")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (1280, 720, "50/1")
    assert float(info["format"]["duration"]) == pytest.approx(4.0, abs=0.1)
    # Clip 1: Originalton + Musik; Clip 2 (stumm): nur Musik; Clip 3: wieder beides.
    assert _tone_level(s.output, 0.5, 440) > 500 and _tone_level(s.output, 0.5, 880) > 300
    assert _tone_level(s.output, 2.2, 440) < 50 and _tone_level(s.output, 2.2, 880) > 300
    assert _tone_level(s.output, 3.4, 440) > 500


def _dialog(tmp_path, monkeypatch, clip_len=1.0, profile="web"):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from fpvcut.ui import render_dialog
    from fpvcut.ui.render_dialog import RenderDialog

    QApplication.instance() or QApplication([])
    # Eigene Einstellungsdatei, damit Tests nicht den echten Render-Ordner verstellen.
    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(render_dialog, "app_settings", lambda: QSettings(ini, QSettings.Format.IniFormat))
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=30",
                    "-c:v", "libx264", "-preset", "ultrafast", str(src)], check=True)
    tl = Timeline([TimelineClip("s", 0, clip_len, has_audio=False, path=src)], render_profile=profile)
    dialog = RenderDialog(tl, SourceFormat(640, 360, 25), Path(shutil.which("ffmpeg")), None)
    dialog._path.setText(str(tmp_path / "ziel" / "out.mp4"))
    return dialog


@needs_ffmpeg
def test_render_dialog_renders_and_reports(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    dialog = _dialog(tmp_path, monkeypatch)
    assert dialog._profile.currentData() == "web"
    assert dialog.encoder() == "libx264"  # ohne Systemcheck: CPU
    assert dialog.settings().width == 640
    assert dialog.start()
    assert dialog.wait()
    QApplication.processEvents()
    assert (tmp_path / "ziel" / "out.mp4").stat().st_size > 0
    assert dialog._status.text().startswith("Fertig")
    assert not dialog._play.isHidden()


@needs_ffmpeg
def test_render_dialog_cancel_removes_file(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    dialog = _dialog(tmp_path, monkeypatch, clip_len=30.0, profile="archiv")
    dialog._resolution.setCurrentIndex(dialog._resolution.findData("3840x2160"))
    assert dialog.start()
    dialog._process.waitForStarted()
    dialog.cancel()
    assert dialog.wait()
    QApplication.processEvents()
    assert not (tmp_path / "ziel" / "out.mp4").exists()
    assert dialog._status.text().startswith("Abgebrochen")
