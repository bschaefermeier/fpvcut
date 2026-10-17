"""ffmpeg finden und prüfen, welche (GPU-)Encoder wirklich funktionieren."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Encoder, die für den Export interessant sind, in Reihenfolge der Bevorzugung.
VIDEO_ENCODERS = {
    "h264": ["h264_nvenc", "libx264"],
    "hevc": ["hevc_nvenc", "libx265"],
    "av1": ["av1_nvenc", "libsvtav1", "libaom-av1"],
}
GPU_ENCODERS = {"h264_nvenc", "hevc_nvenc", "av1_nvenc"}

_ENCODER_LINE = re.compile(r"^\s*([VAS])[.A-Z]{5}\s+(\S+)\s")

# Unter Windows kein Konsolenfenster für jeden ffmpeg-Aufruf öffnen.
_CREATE_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class FFmpegNotFound(RuntimeError):
    pass


def find_tool(name: str) -> Path:
    """Sucht ffmpeg/ffprobe: Umgebungsvariable, ``vendor/ffmpeg`` neben dem Projekt, dann PATH."""
    env = os.environ.get(f"FPVCUT_{name.upper()}")
    candidates = [Path(env)] if env else []
    vendor = Path(__file__).resolve().parents[3] / "vendor" / "ffmpeg"
    candidates += [vendor / f"{name}.exe", vendor / "bin" / f"{name}.exe", vendor / name]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which(name)
    if found:
        return Path(found)
    raise FFmpegNotFound(f"{name} wurde nicht gefunden (PATH, vendor/ffmpeg oder FPVCUT_{name.upper()}).")


def _run(args: list[str], timeout: float = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, creationflags=_CREATE_FLAGS
    )


def parse_encoders(output: str) -> dict[str, set[str]]:
    """Wertet ``ffmpeg -encoders`` aus: {"V": {...}, "A": {...}, "S": {...}}."""
    result: dict[str, set[str]] = {"V": set(), "A": set(), "S": set()}
    in_list = False
    for line in output.splitlines():
        if line.strip().startswith("------"):
            in_list = True
            continue
        if not in_list:
            continue
        match = _ENCODER_LINE.match(line)
        if match:
            result[match.group(1)].add(match.group(2))
    return result


def ffmpeg_version(ffmpeg: Path) -> str:
    first_line = _run([str(ffmpeg), "-hide_banner", "-version"]).stdout.splitlines()[:1]
    return first_line[0] if first_line else "unbekannt"


def encoder_works(ffmpeg: Path, encoder: str) -> bool:
    """Kurzer Testencode. Nötig, weil ffmpeg NVENC auch ohne passende GPU/Treiber auflistet."""
    args = [
        str(ffmpeg), "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=256x256:r=25:d=0.2",
        "-c:v", encoder, "-f", "null", "-",
    ]
    try:
        return _run(args, timeout=20).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


@dataclass
class EncoderReport:
    ffmpeg: Path
    ffprobe: Path | None
    version: str
    listed: set[str] = field(default_factory=set)
    working: set[str] = field(default_factory=set)

    @property
    def gpu_encoders(self) -> list[str]:
        return sorted(self.working & GPU_ENCODERS)

    def best_encoder(self, codec: str) -> str | None:
        """Bester funktionierender Encoder für ``h264``/``hevc``/``av1`` (GPU vor CPU)."""
        return next((e for e in VIDEO_ENCODERS[codec] if e in self.working), None)


def check_encoders(ffmpeg: Path | None = None) -> EncoderReport:
    ffmpeg = ffmpeg or find_tool("ffmpeg")
    try:
        ffprobe: Path | None = find_tool("ffprobe")
    except FFmpegNotFound:
        ffprobe = None
    listed = parse_encoders(_run([str(ffmpeg), "-hide_banner", "-encoders"]).stdout)["V"]
    interesting = {e for names in VIDEO_ENCODERS.values() for e in names} & listed
    working = {e for e in interesting if encoder_works(ffmpeg, e)}
    return EncoderReport(ffmpeg, ffprobe, ffmpeg_version(ffmpeg), listed, working)
