import shutil
import subprocess
from pathlib import Path

import pytest

from fpvcut.timeline.edl import build_edl, build_lavfi
from fpvcut.timeline.model import MIN_CLIP, MusicTrack, Timeline, TimelineClip


def clip(name, src_in, src_out, source=10.0):
    return TimelineClip(name, src_in, src_out, source, f"{name}.mp4", path=Path(f"/v/{name}.mp4"))


def make():
    return Timeline([clip("a", 1, 3), clip("b", 0, 4), clip("c", 5, 6)])


def test_starts_duration_and_clip_at():
    tl = make()
    assert tl.duration == 7
    assert tl.starts() == [0, 2, 6]
    assert tl.clip_at(0) == (0, 0)
    assert tl.clip_at(2.5) == (1, 0.5)
    assert tl.clip_at(7) is None


def test_move_to_gap():
    tl = make()
    assert tl.move(0, 3) == 2  # ans Ende
    assert [c.fingerprint for c in tl.clips] == ["b", "c", "a"]
    assert tl.move(2, 0) == 0
    assert [c.fingerprint for c in tl.clips] == ["a", "b", "c"]
    assert tl.move(1, 1) == 1 and tl.move(1, 2) == 1  # Lücke direkt davor/danach: bleibt


def test_trim_is_clamped():
    tl = make()
    tl.trim_start(0, -5)
    assert tl.clips[0].src_in == 0
    tl.trim_start(0, 99)
    assert tl.clips[0].src_in == pytest.approx(3 - MIN_CLIP)
    tl.trim_end(1, 99)
    assert tl.clips[1].src_out == 10  # nicht länger als die Quelldatei
    tl.trim_end(1, -1)
    assert tl.clips[1].src_out == pytest.approx(MIN_CLIP)


def test_split_keeps_total_length():
    tl = make()
    assert tl.split(3.0) == 2
    assert [(c.fingerprint, c.src_in, c.src_out) for c in tl.clips[1:3]] == [("b", 0, 1), ("b", 1, 4)]
    assert tl.clips[2].path == Path("/v/b.mp4")
    assert tl.duration == 7
    assert tl.split(0.05) is None  # zu nah an der Kante
    assert tl.split(99) is None


def test_save_load_roundtrip(tmp_path):
    tl = make()
    tl.music = MusicTrack("C:/Musik/song.mp3", duration=120, volume=0.5)
    tl.original_volume = 0.3
    tl.save(tmp_path / "t.json")
    loaded = Timeline.load(tmp_path / "t.json")
    assert loaded == tl
    assert all(c.path is None for c in loaded.clips)  # Pfade werden nicht gespeichert
    assert tl.copy().clips[0].path == Path("/v/a.mp4")


def test_music_length():
    tl = make()
    tl.music = MusicTrack("m.mp3", duration=100)
    assert tl.music_length() == 7  # endet mit der Timeline
    tl.music = MusicTrack("m.mp3", duration=5, src_in=1)
    assert tl.music_length() == 4  # Musikstück ist kürzer


def test_edl_and_filter():
    tl = Timeline([clip("a", 1, 3)])
    assert build_edl(tl) == "edl://!new_stream;%8%/v/a.mp4,1.000,2.000"
    assert build_lavfi(tl) == "[vid1]null[vo];[aid1]volume=1.00[ao]"
    tl.music = MusicTrack("/m/x, y.mp3", duration=60, volume=0.5, fade_in=0.5, fade_out=1)
    assert build_edl(tl).endswith(";!new_stream;%11%/m/x, y.mp3,0.000,2.000")
    lavfi = build_lavfi(tl)
    assert "[aid2]volume=0.50,afade=t=in:st=0:d=0.50,afade=t=out:st=1.000:d=1.00[a2]" in lavfi
    assert lavfi.endswith("amix=inputs=2:normalize=0:duration=first[ao]")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg fehlt")
def test_mpv_plays_edl_with_music(tmp_path):
    """Echte Probe mit libmpv: EDL und Filter werden akzeptiert, Länge stimmt."""
    from fpvcut.ui.player import load_mpv

    mpv, _error = load_mpv()
    if mpv is None:
        pytest.skip("libmpv fehlt")
    video, music = tmp_path / "a, 1.mp4", tmp_path / "m.mp3"
    run = ["ffmpeg", "-loglevel", "error", "-y"]
    subprocess.run([*run, "-f", "lavfi", "-i", "testsrc=size=160x90:rate=25:duration=4",
                    "-f", "lavfi", "-i", "sine=f=440:d=4", "-shortest", str(video)], check=True)
    subprocess.run([*run, "-f", "lavfi", "-i", "sine=f=880:d=10", str(music)], check=True)
    tl = Timeline([TimelineClip("a", 0.5, 1.5, 4, path=video), TimelineClip("a", 2, 3, 4, path=video)])
    tl.music = MusicTrack(str(music), duration=10)
    player = mpv.MPV(vo="null", ao="null")
    try:
        player["lavfi-complex"] = build_lavfi(tl)
        player.loadfile(build_edl(tl))
        player.wait_for_property("duration", lambda v: v, timeout=10)
        assert player.duration == pytest.approx(2.0, abs=0.05)
        assert [t["type"] for t in player.track_list].count("audio") == 2
    finally:
        player.terminate()
