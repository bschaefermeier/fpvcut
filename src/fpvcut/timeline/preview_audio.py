"""Originalton der Timeline für die Vorschau vorab in eine WAV-Datei mischen.

mpv kommt mit dem Originalton direkt aus der EDL nicht zurecht: Stumme Clips liefern keinen
Ton, und lange Lücken füllt ``aresample`` zu kurz auf, sodass der Ton späterer Clips zu früh
kommt. Wechselt das Tonformat zwischen zwei Clips, bleibt die Wiedergabe sogar stehen.
Wie beim Rendern bekommt deshalb jeder Clip seinen Ton oder Stille in einheitlichem Format,
und die Vorschau spielt diese eine durchgehende Datei. Das geht schnell, weil nur Ton
decodiert wird, und muss nur nach Änderungen an Clips mit Ton neu gemacht werden.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from fpvcut.core.ffmpeg_tools import CREATE_FLAGS
from fpvcut.timeline.model import Timeline

SAMPLE_RATE = 48000


def build_command(ffmpeg: Path | str, timeline: Timeline, output: Path) -> list[str]:
    """ffmpeg-Befehl für den Originalton aller Clips hintereinander, ohne Lautstärke."""
    args = [str(ffmpeg), "-hide_banner", "-y", "-loglevel", "error", "-nostdin"]
    parts, labels = [], []
    inputs = 0
    for i, clip in enumerate(timeline.clips):
        d = f"{clip.duration:.3f}"
        if clip.has_audio:
            args += ["-ss", f"{clip.src_in:.3f}", "-t", d, "-vn", "-i", str(clip.path)]
            parts.append(
                f"[{inputs}:a]aresample={SAMPLE_RATE},aformat=sample_fmts=s16:channel_layouts=stereo,"
                f"apad,atrim=duration={d},asetpts=PTS-STARTPTS[a{i}]"
            )
            inputs += 1
        else:
            parts.append(f"anullsrc=r={SAMPLE_RATE}:cl=stereo,aformat=sample_fmts=s16,atrim=duration={d}[a{i}]")
        labels.append(f"[a{i}]")
    parts.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[aout]")
    args += ["-filter_complex", ";".join(parts), "-map", "[aout]", "-c:a", "pcm_s16le", str(output)]
    return args


class PreviewAudio:
    """Hält die zuletzt erzeugte Tondatei und erzeugt sie nur bei Änderungen neu."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._key: str | None = None

    @property
    def path(self) -> Path:
        return self.folder / "vorschau_ton.wav"

    @staticmethod
    def key(timeline: Timeline) -> str:
        data = [(str(c.path), round(c.src_in, 3), round(c.duration, 3), c.has_audio) for c in timeline.clips]
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
