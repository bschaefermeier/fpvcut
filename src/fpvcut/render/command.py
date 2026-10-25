"""ffmpeg-Befehl aus einer Timeline bauen.

Jeder Clip ist ein eigener Eingang (``-ss``/``-t`` vor ``-i``, beim Neu-Encodieren
bildgenau). Im ``filter_complex`` wird jeder Clip auf das Zielformat gebracht (skalieren,
schwarze Ränder, fps), Clips ohne Ton bekommen Stille, dann wird alles verkettet, das Bild
am Ende auf Wunsch nach Schwarz ausgeblendet und die Musik dazugemischt.

Clips mit KI-Reinigung bekommen zwei Eingänge: das Bild aus der vorab gereinigten Zwischendatei
(sie enthält genau den Ausschnitt, ab 0) und den Ton aus dem Original.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from fpvcut.core.ffmpeg_tools import GPU_ENCODERS
from fpvcut.timeline.grade import grade_filters
from fpvcut.timeline.model import Timeline

SAMPLE_RATE = 48000
DEFAULT_FORMAT = (1280, 720, 50.0)


@dataclass(frozen=True)
class SourceFormat:
    width: int
    height: int
    fps: float


@dataclass
class RenderSettings:
    output: Path
    width: int
    height: int
    fps: float
    encoder: str  # z. B. hevc_nvenc oder libx264
    quality: int
    audio_bitrate: str = "192k"
    ten_bit: bool = False
    faststart: bool = True


def source_format(timeline: Timeline, formats: list[SourceFormat | None]) -> SourceFormat:
    """Häufigstes Format der Clips, gewichtet nach Länge auf der Timeline."""
    weights: Counter[SourceFormat] = Counter()
    for clip, fmt in zip(timeline.clips, formats):
        if fmt is not None and fmt.width and fmt.height and fmt.fps:
            weights[SourceFormat(fmt.width, fmt.height, round(fmt.fps, 3))] += clip.duration
    if not weights:
        return SourceFormat(*DEFAULT_FORMAT)
    return weights.most_common(1)[0][0]


def _even(value: int) -> int:
    return max(2, value - value % 2)


def encoder_args(settings: RenderSettings) -> list[str]:
    enc, q = settings.encoder, str(settings.quality)
    args = ["-c:v", enc]
    if enc in GPU_ENCODERS:
        args += ["-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", q, "-b:v", "0", "-spatial-aq", "1"]
        if enc == "hevc_nvenc" and settings.ten_bit:
            args += ["-profile:v", "main10"]
    elif enc == "libx264":
        args += ["-preset", "medium", "-crf", q]
    elif enc == "libx265":
        args += ["-preset", "medium", "-crf", q, "-x265-params", "log-level=error"]
    else:
        args += ["-crf", q]
    if enc.startswith("hevc") or enc == "libx265":
        args += ["-tag:v", "hvc1"]  # damit Apple-Geräte und Browser H.265 in MP4 erkennen
    return args


def clip_inputs(timeline: Timeline, restored: dict[int, Path] | None = None) -> tuple[list[str], list[tuple[int, int]]]:
    """ffmpeg-Eingänge der Clips und je Clip die Nummern der Eingänge für Bild und Ton."""
    restored = restored or {}
    args, streams = [], []
    for index, clip in enumerate(timeline.clips):
        original = ["-ss", f"{clip.src_in:.3f}", "-t", f"{clip.duration:.3f}", "-i", str(clip.path)]
        video = args.count("-i")
        if index in restored:
            args += ["-t", f"{clip.duration:.3f}", "-i", str(restored[index])]
            if clip.has_audio:
                args += original
            streams.append((video, video + 1 if clip.has_audio else video))
        else:
            args += original
            streams.append((video, video))
    return args, streams


def build_filter(timeline: Timeline, settings: RenderSettings, streams: list[tuple[int, int]] | None = None) -> str:
    """``streams``: Eingänge je Clip (Bild, Ton) aus :func:`clip_inputs`; ohne Angabe einer je Clip."""
    w, h = _even(settings.width), _even(settings.height)
    streams = streams or [(i, i) for i in range(len(timeline.clips))]
    pix_fmt = "p010le" if settings.ten_bit and settings.encoder == "hevc_nvenc" else (
        "yuv420p10le" if settings.ten_bit else "yuv420p"
    )
    parts, pairs = [], []
    for i, clip in enumerate(timeline.clips):
        d = f"{clip.duration:.3f}"
        # Farbkorrektur vor dem Skalieren, damit schwarze Ränder schwarz bleiben.
        grade = "".join(f"{f}," for f in grade_filters(clip.grade))
        parts.append(
            f"[{streams[i][0]}:v]{grade}scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={settings.fps:g},format={pix_fmt},"
            f"trim=duration={d},setpts=PTS-STARTPTS[v{i}]"
        )
        if clip.has_audio:
            parts.append(
                f"[{streams[i][1]}:a]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,"
                f"apad,atrim=duration={d},asetpts=PTS-STARTPTS[a{i}]"
            )
        else:
            parts.append(f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=duration={d}[a{i}]")
        pairs.append(f"[v{i}][a{i}]")
    n = len(timeline.clips)
    music_input = (max(max(pair) for pair in streams) + 1) if streams else 0
    fade = timeline.video_fade()
    parts.append(f"{''.join(pairs)}concat=n={n}:v=1:a=1[{'vcat' if fade else 'vout'}][acat]")
    if fade:
        parts.append(f"[vcat]fade=t=out:st={fade[0]:.3f}:d={fade[1]:.2f}:color=black[vout]")
    parts.append(f"[acat]volume={timeline.original_volume:.2f}[aorig]")

    music, length = timeline.music, timeline.music_length()
    if music is not None and length > 0:
        filters = [f"aresample={SAMPLE_RATE}", "aformat=channel_layouts=stereo", f"volume={music.volume:.2f}"]
        if music.fade_in > 0:
            filters.append(f"afade=t=in:st=0:d={min(music.fade_in, length):.2f}")
        if music.fade_out > 0:
            fade = min(music.fade_out, length)
            filters.append(f"afade=t=out:st={length - fade:.3f}:d={fade:.2f}")
        parts.append(f"[{music_input}:a]{','.join(filters)}[amusic]")
        parts.append("[aorig][amusic]amix=inputs=2:normalize=0:duration=first[aout]")
    else:
        parts[-1] = parts[-1].replace("[aorig]", "[aout]")
    return ";".join(parts)


def build_command(ffmpeg: Path | str, timeline: Timeline, settings: RenderSettings,
                  restored: dict[int, Path] | None = None) -> list[str]:
    """``restored``: gereinigte Zwischendateien je Clip-Index (siehe :mod:`fpvcut.restore.render`)."""
    args = [str(ffmpeg), "-hide_banner", "-y", "-loglevel", "error", "-nostats", "-progress", "pipe:1"]
    inputs, streams = clip_inputs(timeline, restored)
    args += inputs
    music, length = timeline.music, timeline.music_length()
    if music is not None and length > 0:
        args += ["-ss", f"{music.src_in:.3f}", "-t", f"{length:.3f}", "-i", music.path]
    args += ["-filter_complex", build_filter(timeline, settings, streams), "-map", "[vout]", "-map", "[aout]"]
    args += encoder_args(settings)
    args += ["-c:a", "aac", "-b:a", settings.audio_bitrate, "-ar", str(SAMPLE_RATE)]
    if settings.faststart:
        args += ["-movflags", "+faststart"]
    args += [str(settings.output)]
    return args


def parse_progress(line: str) -> float | None:
    """Sekunden aus einer ``-progress``-Zeile (``out_time_us=…``), sonst None."""
    key, _, value = line.strip().partition("=")
    if key in ("out_time_us", "out_time_ms") and value.lstrip("-").isdigit():
        return max(int(value), 0) / 1_000_000  # beide Felder sind in Mikrosekunden
    return None
