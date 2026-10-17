import shutil

import pytest

from fpvcut.core.ffmpeg_tools import EncoderReport, check_encoders, encoder_works, find_tool, parse_encoders

SAMPLE = """Encoders:
 V..... = Video
 A..... = Audio
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC (codec h264)
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)
 V....D hevc_nvenc           NVIDIA NVENC hevc encoder (codec hevc)
 A....D aac                  AAC (Advanced Audio Coding)
 S..... srt                  SubRip subtitle
"""

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg nicht installiert")


def test_parse_encoders_splits_by_type():
    parsed = parse_encoders(SAMPLE)
    assert parsed["V"] == {"libx264", "h264_nvenc", "hevc_nvenc"}
    assert parsed["A"] == {"aac"}
    assert parsed["S"] == {"srt"}


def test_legend_lines_are_ignored():
    assert "=" not in parse_encoders(SAMPLE)["V"]


def test_best_encoder_prefers_gpu():
    report = EncoderReport(ffmpeg=None, ffprobe=None, version="", working={"libx264", "h264_nvenc", "libx265"})
    assert report.best_encoder("h264") == "h264_nvenc"
    assert report.best_encoder("hevc") == "libx265"
    assert report.best_encoder("av1") is None
    assert report.gpu_encoders == ["h264_nvenc"]


def test_find_tool_honours_env(tmp_path, monkeypatch):
    fake = tmp_path / "ffmpeg.exe"
    fake.write_text("")
    monkeypatch.setenv("FPVCUT_FFMPEG", str(fake))
    assert find_tool("ffmpeg") == fake


@needs_ffmpeg
def test_cpu_encoder_works():
    assert encoder_works(find_tool("ffmpeg"), "libx264")


@needs_ffmpeg
def test_unknown_encoder_fails_cleanly():
    assert not encoder_works(find_tool("ffmpeg"), "does_not_exist")


@needs_ffmpeg
def test_check_encoders_only_reports_working():
    report = check_encoders()
    assert report.working <= report.listed
    assert report.best_encoder("h264") is not None
