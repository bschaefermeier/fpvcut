import sys
from pathlib import Path

from fpvcut import app
from fpvcut.core import paths


def test_vendor_dir_from_source_tree():
    assert paths.vendor_dir("mpv") == Path(__file__).resolve().parents[1] / "vendor" / "mpv"


def test_vendor_dir_in_frozen_exe(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    assert paths.vendor_dir("ffmpeg") == tmp_path / "_internal" / "vendor" / "ffmpeg"


def test_self_test_writes_report(monkeypatch, tmp_path):
    monkeypatch.setenv("FPVCUT_FFMPEG", str(tmp_path / "fehlt.exe"))
    monkeypatch.setenv("FPVCUT_FFPROBE", str(tmp_path / "fehlt.exe"))
    monkeypatch.setenv("PATH", "")
    report = tmp_path / "selbsttest.txt"
    assert app.self_test(report) == 1
    text = report.read_text(encoding="utf-8")
    assert text.startswith("FPVCut ")
    assert "ffmpeg: FEHLER" in text
    assert "Icon: OK" in text
