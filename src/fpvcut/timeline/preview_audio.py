"""Ton der Timeline für die Vorschau vorab in eine WAV-Datei mischen.

mpv kommt mit dem Ton direkt aus der EDL nicht zurecht, wenn er erst in ``lavfi-complex``
gemischt wird: Lange stumme Strecken im Originalton werden zu kurz aufgefüllt, ein Wechsel
des Tonformats zwischen Clips hält die Wiedergabe an, und nach einem Sprung läuft die Musik
versetzt und endet zu früh. Deshalb mischt ffmpeg den Ton wie beim Rendern: Jeder Clip
bringt seinen Ton oder Stille mit, dazu kommt die Musik mit Lautstärke und Blenden. mpv
spielt diese eine Datei als ganz normale Tonspur und springt darin genau. Das geht schnell,
weil nur Ton decodiert wird, und passiert nur nach Änderungen, die den Ton betreffen.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from fpvcut.core.ffmpeg_tools import CREATE_FLAGS
from fpvcut.timeline.model import Timeline

SAMPLE_RATE = 48000


def has_audio(timeline: Timeline) -> bool:
    return timeline.has_original_audio or (timeline.music is not None and timeline.music_length() > 0)


def build_command(ffmpeg: Path | str, timeline: Timeline, output: Path) -> list[str]:
    """ffmpeg-Befehl für den fertig gemischten Ton der Timeline."""
    args = [str(ffmpeg), "-hide_banner", "-y", "-loglevel", "error", "-nostdin"]
    parts, labels = [], []
    inputs = 0
    for i, clip in enumerate(timeline.clips):
        d = f"{clip.duration:.3f}"
        if clip.has_audio:
            args += ["-ss", f"{clip.src_in:.3f}", "-t", d, "-vn", "-i", str(clip.path)]
            parts.append(
                f"[{inputs}:a]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,"
                f"apad,atrim=duration={d},asetpts=PTS-STARTPTS[a{i}]"
            )
            inputs += 1
        else:
            parts.append(f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=duration={d}[a{i}]")
        labels.append(f"[a{i}]")
    parts.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1,volume={timeline.original_volume:.2f}[aorig]")

    music, length = timeline.music, timeline.music_length()
    if music is not None and length > 0:
        args += ["-ss", f"{music.src_in:.3f}", "-t", f"{length:.3f}", "-vn", "-i", music.path]
        filters = [f"aresample={SAMPLE_RATE}", "aformat=channel_layouts=stereo", f"volume={music.volume:.2f}"]
        if music.fade_in > 0:
            filters.append(f"afade=t=in:st=0:d={min(music.fade_in, length):.2f}")
        if music.fade_out > 0:
            fade = min(music.fade_out, length)
            filters.append(f"afade=t=out:st={length - fade:.3f}:d={fade:.2f}")
        parts.append(f"[{inputs}:a]{','.join(filters)}[amusic]")
        parts.append("[aorig][amusic]amix=inputs=2:normalize=0:duration=first[aout]")
    else:
        parts[-1] = parts[-1].replace("[aorig]", "[aout]")
    args += ["-filter_complex", ";".join(parts), "-map", "[aout]", "-c:a", "pcm_s16le", str(output)]
    return args


class PreviewAudio:
    """Hält die zuletzt gemischte Tondatei und mischt sie nur bei Änderungen neu."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._key: str | None = None

    @property
    def path(self) -> Path:
        return self.folder / "vorschau_ton.wav"

    @staticmethod
    def key(timeline: Timeline) -> str:
        """Alles, was den Ton bestimmt; Farbkorrektur und Ähnliches ändern ihn nicht."""
        data = {
            "clips": [(str(c.path), round(c.src_in, 3), round(c.duration, 3), c.has_audio) for c in timeline.clips],
            "original_volume": round(timeline.original_volume, 2),
            "music": asdict(timeline.music) if timeline.music else None,
            "music_length": round(timeline.music_length(), 3),
        }
        return hashlib.sha1(json.dumps(data).encode()).hexdigest()

    def get(self, ffmpeg: Path | str, timeline: Timeline) -> Path:
        """Pfad der Tondatei; wirft ``OSError`` oder ``subprocess.SubprocessError``, wenn ffmpeg scheitert."""
        key = self.key(timeline)
        if key == self._key and self.path.exists():
            return self.path
        self._key = None
        self.folder.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            build_command(ffmpeg, timeline, self.path),
            capture_output=True, text=True, timeout=300, creationflags=CREATE_FLAGS, check=False,
        )
        if result.returncode != 0:
            raise subprocess.SubprocessError(result.stderr.strip() or f"ffmpeg-Fehler {result.returncode}")
        self._key = key
        return self.path
