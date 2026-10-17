"""Video-Metadaten per ffprobe."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from fpvcut.core.ffmpeg_tools import CREATE_FLAGS


@dataclass
class MediaInfo:
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    vcodec: str | None = None
    bit_depth: int | None = None
    acodec: str | None = None
    raw: dict | None = None


def _parse_rate(rate: str | None) -> float | None:
    try:
        value = float(Fraction(rate)) if rate else None
    except (ValueError, ZeroDivisionError):
        return None
    return round(value, 3) if value else None


def _bit_depth(stream: dict) -> int | None:
    raw = stream.get("bits_per_raw_sample")
    if raw and str(raw).isdigit():
        return int(raw)
    pix_fmt = stream.get("pix_fmt") or ""
    for depth in (10, 12):
        if f"p{depth}" in pix_fmt:
            return depth
    return 8 if pix_fmt else None


def parse_probe(data: dict) -> MediaInfo:
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = data.get("format", {}).get("duration") or (video or {}).get("duration")
    info = MediaInfo(duration=float(duration) if duration else None, raw=data)
    if video:
        info.width = video.get("width")
        info.height = video.get("height")
        info.fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate"))
        info.vcodec = video.get("codec_name")
        info.bit_depth = _bit_depth(video)
    if audio:
        info.acodec = audio.get("codec_name")
    return info


def probe(ffprobe: Path, path: Path) -> MediaInfo | None:
    """Liest Metadaten; ``None``, wenn ffprobe die Datei nicht lesen kann."""
    args = [str(ffprobe), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=60, creationflags=CREATE_FLAGS)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        return parse_probe(json.loads(result.stdout))
    except json.JSONDecodeError:
        return None
