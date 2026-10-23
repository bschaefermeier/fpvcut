import array
import cmath
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from fpvcut.timeline import preview_audio
from fpvcut.timeline.edl import build_edl, build_vf
from fpvcut.timeline.model import MIN_CLIP, MusicTrack, Timeline, TimelineClip


def clip(name, src_in, src_out, source=10.0):
    return TimelineClip(name, src_in, src_out, source, f"{name}.mp4", path=Path(f"/v/{name}.mp4"))


def src(name):
    """Pfad eines Testclips, wie ihn das Betriebssystem schreibt (unter Windows mit Backslashes)."""
    return str(Path(f"/v/{name}.mp4"))


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


def test_excerpt_cuts_clips_and_shifts_music():
    tl = make()  # a: 0–2, b: 2–6, c: 6–7 auf der Timeline
    tl.clips[1].grade = {"contrast": 1.2}
    tl.music = MusicTrack("m.mp3", duration=100, src_in=10, fade_in=2, fade_out=3)
    part = tl.excerpt(1.5, 6.5)
    assert [(c.fingerprint, c.src_in, c.src_out) for c in part.clips] == [
        ("a", 2.5, 3), ("b", 0, 4), ("c", 5, 5.5)]
    assert part.duration == pytest.approx(5)
    assert part.clips[1].grade == {"contrast": 1.2} and part.clips[0].path == Path("/v/a.mp4")
    assert (part.music.src_in, part.music.fade_in, part.music.fade_out) == (11.5, 0, 3)
    assert tl.duration == 7 and tl.clips[0].src_in == 1  # Original bleibt unverändert
    assert tl.excerpt(0, 2).music.fade_in == 2  # ab Anfang: Einblenden bleibt
    assert [c.fingerprint for c in tl.excerpt(2, 6).clips] == ["b"]  # Grenzen genau auf Schnitten


def test_video_fade_at_end_also_in_excerpt_and_saved(tmp_path):
    tl = make()  # 7 s lang
    assert tl.video_fade() is None
    tl.video_fade_out = 2
    assert tl.video_fade() == (5, 2)
    assert tl.excerpt(1, 4).video_fade() == (1, 2)  # blendet am Ende des Bereichs aus
    tl.video_fade_out = 30
    assert tl.video_fade() == (0, 7)  # nie länger als die Timeline
    tl.save(tmp_path / "t.json")
    assert Timeline.load(tmp_path / "t.json").video_fade_out == 30
    assert Timeline.from_dict({"video_track": []}).video_fade_out == 0  # ältere Dateien


def test_preview_fades_picture_to_black():
    tl = make()
    assert build_vf(tl) == ""
    tl.video_fade_out = 1.5
    assert build_vf(tl).endswith(",fade=t=out:st=5.500:d=1.50:color=black]")


def test_excerpt_drops_music_that_already_ended():
    tl = make()
    tl.music = MusicTrack("m.mp3", duration=3)
    assert tl.excerpt(4, 7).music is None


def test_edl_puts_mixed_audio_first():
    tl = Timeline([clip("a", 1, 3), clip("b", 0, 1)])
    assert build_edl(tl) == f"edl://!new_stream;%8%{src('a')},1.000,2.000;%8%{src('b')},0.000,1.000"
    # Der gemischte Ton steht vorn und ist damit immer aid1.
    assert build_edl(tl, "/t/o.wav") == (
        f"edl://!new_stream;%8%/t/o.wav,0.000,3.000;!new_stream;%8%{src('a')},1.000,2.000;%8%{src('b')},0.000,1.000"
    )


def test_preview_audio_command_mixes_like_render(tmp_path):
    tl = Timeline([clip("a", 1, 3), TimelineClip("b", 0, 2, path=Path("/v/b.mp4"), has_audio=False)])
    tl.original_volume = 0.5
    cmd = preview_audio.build_command("ffmpeg", tl, tmp_path / "o.wav")
    i = cmd.index("-i")
    assert cmd[i - 5:i + 2] == ["-ss", "1.000", "-t", "2.000", "-vn", "-i", src("a")]
    assert cmd.count("-i") == 1  # nur Clips mit Ton werden gelesen
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "[0:a]aresample=48000" in graph and "anullsrc=r=48000:cl=stereo" in graph
    assert graph.endswith("[a0][a1]concat=n=2:v=0:a=1,volume=0.50[aout]")

    tl.music = MusicTrack("/m/x, y.mp3", duration=60, src_in=5, volume=0.8, fade_in=0.5, fade_out=1)
    cmd = preview_audio.build_command("ffmpeg", tl, tmp_path / "o.wav")
    assert cmd[cmd.index("/m/x, y.mp3") - 6:cmd.index("/m/x, y.mp3")] == ["-ss", "5.000", "-t", "4.000", "-vn", "-i"]
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "[1:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.80,afade=t=in:st=0:d=0.50," \
           "afade=t=out:st=3.000:d=1.00[amusic]" in graph
    assert graph.endswith("[aorig][amusic]amix=inputs=2:normalize=0:duration=first[aout]")
    assert preview_audio.has_audio(tl)
    tl.clips[0].has_audio = False
    tl.music = None
    assert not preview_audio.has_audio(tl)


def _mpv():
    from fpvcut.ui.player import load_mpv

    mpv, _error = load_mpv()
    if mpv is None:
        pytest.skip("libmpv fehlt")
    return mpv


def _play(mpv, tl, tmp_path, start=0.0, out=None):
    from fpvcut.ui.player import quote_option

    audio = preview_audio.PreviewAudio(tmp_path / "vorschau").get("ffmpeg", tl)
    options = {"ao": "pcm", "ao_pcm_file": str(out)} if out else {"ao": "null"}
    player = mpv.MPV(vo="null", keep_open="yes", **options)
    try:
        vf = build_vf(tl)
        player.loadfile(build_edl(tl, audio), start=str(start), aid="1", **({"vf": quote_option(vf)} if vf else {}))
        player.wait_for_property("eof-reached", lambda v: v, timeout=30)
        return player.time_pos, [t["type"] for t in player.track_list if t.get("selected")]
    finally:
        player.terminate()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg fehlt")
def test_mpv_plays_edl_with_music(tmp_path):
    """Echte Probe mit libmpv: EDL und gemischter Ton werden abgespielt, Länge stimmt."""
    mpv = _mpv()
    video, music = tmp_path / "a, 1.mp4", tmp_path / "m.mp3"
    run = ["ffmpeg", "-loglevel", "error", "-y"]
    subprocess.run([*run, "-f", "lavfi", "-i", "testsrc=size=160x90:rate=25:duration=4",
                    "-f", "lavfi", "-i", "sine=f=440:d=4", "-shortest", str(video)], check=True)
    subprocess.run([*run, "-f", "lavfi", "-i", "sine=f=880:d=10", str(music)], check=True)
    tl = Timeline([TimelineClip("a", 0.5, 1.5, 4, path=video), TimelineClip("a", 2, 3, 4, path=video)])
    tl.music = MusicTrack(str(music), duration=10)
    end, selected = _play(mpv, tl, tmp_path)
    assert end == pytest.approx(2.0, abs=0.05)
    assert sorted(selected) == ["audio", "video"]


def _tone(samples: array.array, freqs) -> int | None:
    """Lauteste der Frequenzen in einem Mono-Ausschnitt (48 kHz), None bei Stille."""
    levels = {
        f: abs(sum(v * cmath.exp(-2j * math.pi * f * i / 48000) for i, v in enumerate(samples))) / len(samples)
        for f in freqs
    }
    best = max(levels, key=levels.get)
    return best if levels[best] > 300 else None


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg fehlt")
def test_mpv_sound_stays_in_sync_after_far_jump(tmp_path):
    """Sprung weit in die Timeline hinter eine lange stumme Strecke: Musik und Originalton stimmen.

    Mit dem Ton aus ``lavfi-complex`` lief die Musik hier versetzt und endete zu früh, und
    der Originalton späterer Clips kam zu früh.
    """
    mpv = _mpv()
    loud, silent, music = tmp_path / "loud.avi", tmp_path / "silent.mp4", tmp_path / "music.mp3"
    out = tmp_path / "out.wav"
    run = ["ffmpeg", "-loglevel", "error", "-y"]
    subprocess.run([*run, "-f", "lavfi", "-i", "testsrc=size=160x90:rate=25:duration=3", "-f", "lavfi",
                    "-i", "sine=f=2000:d=3:sample_rate=44100", "-c:v", "mjpeg", "-c:a", "pcm_s16le", str(loud)],
                   check=True)
    subprocess.run([*run, "-f", "lavfi", "-i", "testsrc=size=160x90:rate=25:duration=60",
                    "-c:v", "libx264", "-preset", "ultrafast", str(silent)], check=True)
    # Alle 10 Sekunden hat die Musik ihren eigenen Ton: 300 Hz, 400 Hz, ...
    subprocess.run([*run, "-f", "lavfi", "-i", "aevalsrc=sin(2*PI*(300+100*floor(t/10))*t):d=90:s=44100",
                    "-c:a", "libmp3lame", "-q:a", "4", str(music)], check=True)
    tl = Timeline([TimelineClip("a", 0, 2, 3, path=loud), TimelineClip("s", 0, 60, 60, path=silent, has_audio=False),
                   TimelineClip("a", 0, 2, 3, path=loud)])
    tl.music = MusicTrack(str(music), duration=90, volume=1, fade_out=0)
    start = 50.1
    end, _selected = _play(mpv, tl, tmp_path, start, out)
    assert end == pytest.approx(64.0, abs=0.1)
    for t in (50.4, 55.4, 61.4, 62.4, 63.4):
        raw = subprocess.run([*run, "-ss", str(t - start), "-t", "0.05", "-i", str(out), "-ac", "1",
                              "-ar", "48000", "-f", "s16le", "-"], capture_output=True, check=True).stdout
        samples = array.array("h", raw)
        assert _tone(samples, range(300, 1100, 100)) == 300 + 100 * math.floor(t / 10), f"Musik bei {t} s"
        assert _tone(samples, (2000,)) == (None if t < 62 else 2000), f"Originalton bei {t} s"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg fehlt")
def test_mpv_plays_through_format_change(tmp_path):
    """Wechsel von Codec, Auflösung, Bildrate und Tonformat zwischen Clips: Die Vorschau läuft bis zum Ende.

    Lief das Bild durch ``lavfi-complex`` oder kam der Originalton direkt aus der EDL, blieb mpv
    beim ersten Formatwechsel stehen.
    """
    mpv = _mpv()
    a, b, c, music = tmp_path / "a.mp4", tmp_path / "b.ts", tmp_path / "c.avi", tmp_path / "m.mp3"
    run = ["ffmpeg", "-loglevel", "error", "-y"]
    subprocess.run([*run, "-f", "lavfi", "-i", "testsrc=size=160x90:rate=50:duration=2",
                    "-c:v", "libx264", "-preset", "ultrafast", str(a)], check=True)
    subprocess.run([*run, "-f", "lavfi", "-i", "testsrc2=size=192x108:rate=30:duration=2", "-f", "lavfi",
                    "-i", "sine=d=2:sample_rate=44100", "-c:v", "mpeg2video", "-c:a", "mp2", "-f", "mpegts", str(b)],
                   check=True)
    subprocess.run([*run, "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=2", "-f", "lavfi",
                    "-i", "sine=d=2:sample_rate=48000", "-ac", "2", "-c:v", "mjpeg", "-c:a", "pcm_s16le", str(c)],
                   check=True)
    subprocess.run([*run, "-f", "lavfi", "-i", "sine=f=880:d=10", str(music)], check=True)
    grade = {"saturation": 1.2}
    tl = Timeline([TimelineClip("a", 0, 1, 2, path=a, has_audio=False, grade=grade),
                   TimelineClip("b", 0, 1, 2, path=b, grade=grade),
                   TimelineClip("a", 1, 2, 2, path=a, has_audio=False, grade=grade),
                   TimelineClip("c", 0, 1, 2, path=c, grade=grade)])
    tl.music = MusicTrack(str(music), duration=10)
    end, _selected = _play(mpv, tl, tmp_path)
    assert end == pytest.approx(4.0, abs=0.1)


def test_preview_audio_is_only_mixed_again_after_changes(monkeypatch, tmp_path):
    runs = []

    def fake_run(args, **_kwargs):
        runs.append(args)
        Path(args[-1]).write_bytes(b"wav")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(preview_audio.subprocess, "run", fake_run)
    audio = preview_audio.PreviewAudio(tmp_path)
    tl = Timeline([clip("a", 1, 3), clip("b", 0, 2)])
    audio.get("ffmpeg", tl)
    tl.clips[0].grade = {"saturation": 0.5}  # Farbe ändert den Ton nicht
    audio.get("ffmpeg", tl)
    assert len(runs) == 1
    for change in (lambda: setattr(tl.clips[1], "src_out", 1.5), lambda: setattr(tl, "original_volume", 0.3),
                   lambda: setattr(tl, "music", MusicTrack("/m.mp3", 60))):
        change()
        audio.get("ffmpeg", tl)
    assert len(runs) == 4

    monkeypatch.setattr(preview_audio.subprocess, "run",
                        lambda args, **_k: subprocess.CompletedProcess(args, 1, "", "kaputt"))
    tl.clips[1].src_out = 1.0
    with pytest.raises(subprocess.SubprocessError, match="kaputt"):
        audio.get("ffmpeg", tl)
