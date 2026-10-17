import shutil
import subprocess

import pytest

from fpvcut.core import scanner
from fpvcut.core.ffmpeg_tools import find_tool
from fpvcut.core.library import Library
from fpvcut.core.probe import MediaInfo, probe
from fpvcut.core.scanner import scan_library


def fake_probe(_path):
    return MediaInfo(duration=1.0, width=1280, height=720, fps=50.0, vcodec="h264")


@pytest.fixture
def lib(tmp_path):
    library = Library(tmp_path / "db" / "library.sqlite")
    yield library
    library.close()


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def by_name(library):
    return {e.rel_path: e for e in library.entries()}


def test_new_files_are_found_and_marked_new(lib, tmp_path):
    root = tmp_path / "FPV"
    write(root / "28_08_26_Wiese" / "a.mp4", b"aaa")
    write(root / "28_08_26_Wiese" / "notes.txt", b"kein Video")
    lib.add_root(root)
    result = scan_library(lib, fake_probe)
    assert result.new == 1
    entry = by_name(lib)["28_08_26_Wiese/a.mp4"]
    assert entry.is_new and entry.width == 1280
    assert entry.flight_day.canonical_name == "2026_08_28_Wiese"


def test_unchanged_files_are_not_rehashed(lib, tmp_path, monkeypatch):
    root = tmp_path / "FPV"
    write(root / "day" / "a.mp4", b"aaa")
    lib.add_root(root)
    scan_library(lib, fake_probe)

    calls = []
    monkeypatch.setattr(scanner, "fingerprint", lambda p: calls.append(p))
    result = scan_library(lib, fake_probe)
    assert result.unchanged == 1 and calls == []


def test_renamed_folder_keeps_media_and_review_state(lib, tmp_path):
    root = tmp_path / "FPV"
    write(root / "28_08_26_Wiese" / "a.mp4", b"aaa")
    lib.add_root(root)
    scan_library(lib, fake_probe)
    media_id = by_name(lib)["28_08_26_Wiese/a.mp4"].media_id
    lib.set_reviewed([media_id])

    (root / "28_08_26_Wiese").rename(root / "2026_08_28_Wiese")
    result = scan_library(lib, fake_probe)

    entries = by_name(lib)
    assert list(entries) == ["2026_08_28_Wiese/a.mp4"]
    moved = entries["2026_08_28_Wiese/a.mp4"]
    assert moved.media_id == media_id and not moved.is_new and not moved.missing
    assert result.new == 0 and result.rehashed == 1 and result.missing == 0


def test_move_between_roots(lib, tmp_path):
    old_root, new_root = tmp_path / "alt", tmp_path / "neu"
    write(old_root / "d" / "a.mp4", b"aaa")
    new_root.mkdir()
    lib.add_root(old_root)
    lib.add_root(new_root)
    scan_library(lib, fake_probe)
    media_id = lib.entries()[0].media_id

    shutil.move(old_root / "d", new_root / "d")
    scan_library(lib, fake_probe)
    [entry] = lib.entries()
    assert entry.media_id == media_id and entry.root_path == new_root.resolve()


def test_deleted_file_is_missing_but_kept(lib, tmp_path):
    root = tmp_path / "FPV"
    write(root / "d" / "a.mp4", b"aaa")
    lib.add_root(root)
    scan_library(lib, fake_probe)
    (root / "d" / "a.mp4").unlink()

    result = scan_library(lib, fake_probe)
    [entry] = lib.entries()
    assert entry.missing and result.missing == 1

    write(root / "zurueck" / "a.mp4", b"aaa")  # Datei taucht woanders wieder auf
    scan_library(lib, fake_probe)
    [entry] = lib.entries()
    assert not entry.missing and entry.rel_path == "zurueck/a.mp4"


def test_unreachable_root_marks_nothing_missing(lib, tmp_path):
    root = tmp_path / "Platte"
    write(root / "d" / "a.mp4", b"aaa")
    lib.add_root(root)
    scan_library(lib, fake_probe)
    shutil.rmtree(root)  # wie eine abgesteckte externe Platte

    result = scan_library(lib, fake_probe)
    assert result.errors and not lib.entries()[0].missing


def test_duplicate_counts_once(lib, tmp_path):
    root = tmp_path / "FPV"
    write(root / "a" / "clip.mp4", b"same")
    write(root / "b" / "clip.mp4", b"same")
    lib.add_root(root)
    result = scan_library(lib, fake_probe)
    assert result.new == 1 and result.rehashed == 1
    assert len(lib.entries()) == 1


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe nicht installiert")
def test_real_probe_720p50(tmp_path):
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [str(find_tool("ffmpeg")), "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=50:d=1",
         "-f", "lavfi", "-i", "sine=d=1", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(clip)],
        check=True,
    )
    info = probe(find_tool("ffprobe"), clip)
    assert (info.width, info.height, info.fps, info.vcodec, info.acodec) == (1280, 720, 50.0, "h264", "aac")
    assert info.bit_depth == 8 and info.duration == pytest.approx(1.0, abs=0.1)
