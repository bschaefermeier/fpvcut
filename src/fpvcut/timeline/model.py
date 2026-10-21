"""Timeline-Modell: eine Videospur aus Ausschnitten plus optional eine Musikspur.

Clips hängen wie Favoriten am Fingerprint, nicht am Pfad. Der Pfad wird beim Laden
über die Bibliothek aufgelöst und nicht gespeichert.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fpvcut.i18n import translate

FORMAT_VERSION = 1
MIN_CLIP = 0.2  # kürzer als 0,2 s lässt sich ein Clip nicht trimmen oder teilen


@dataclass
class TimelineClip:
    fingerprint: str
    src_in: float
    src_out: float
    source_duration: float | None = None  # Länge der Quelldatei, Grenze fürs Trimmen
    label: str = ""  # Dateiname zur Anzeige, auch wenn die Datei gerade fehlt
    has_audio: bool = True
    # Ursprünglicher Favoriten-Ausschnitt; was beim Trimmen darüber hinausgeht, wird anders eingefärbt.
    fav_in: float | None = None
    fav_out: float | None = None
    grade: dict | None = None  # Farbkorrektur, siehe timeline/grade.py
    path: Path | None = field(default=None, compare=False)  # zur Laufzeit aufgelöst

    @property
    def duration(self) -> float:
        return self.src_out - self.src_in

    def to_dict(self) -> dict:
        data = asdict(self)
        del data["path"]
        return data


@dataclass
class MusicTrack:
    path: str
    duration: float | None = None  # Länge der Musikdatei
    src_in: float = 0.0  # ab hier im Musikstück beginnen
    volume: float = 0.8
    fade_in: float = 0.0
    fade_out: float = 3.0

    @property
    def name(self) -> str:
        return Path(self.path).name


@dataclass
class Timeline:
    clips: list[TimelineClip] = field(default_factory=list)
    music: MusicTrack | None = None
    original_volume: float = 1.0  # Originalton aller Clips
    render_profile: str = "web"

    # --- Abfragen --------------------------------------------------------

    @property
    def duration(self) -> float:
        return sum(c.duration for c in self.clips)

    def starts(self) -> list[float]:
        """Startzeit jedes Clips auf der Timeline."""
        result, t = [], 0.0
        for clip in self.clips:
            result.append(t)
            t += clip.duration
        return result

    def clip_at(self, t: float) -> tuple[int, float] | None:
        """Index des Clips an Timeline-Zeit ``t`` und die Position darin."""
        for index, start in enumerate(self.starts()):
            clip = self.clips[index]
            if start <= t < start + clip.duration:
                return index, t - start
        return None

    def music_length(self) -> float:
        """So lange läuft die Musik: bis zum Ende der Timeline oder des Musikstücks."""
        if self.music is None:
            return 0.0
        available = self.duration if self.music.duration is None else self.music.duration - self.music.src_in
        return max(min(available, self.duration), 0.0)

    @property
    def has_original_audio(self) -> bool:
        return any(c.has_audio for c in self.clips)

    def missing_clips(self) -> list[TimelineClip]:
        return [c for c in self.clips if c.path is None]

    # --- Bearbeiten ------------------------------------------------------

    def insert(self, clips: list[TimelineClip], index: int | None = None) -> None:
        index = len(self.clips) if index is None else max(0, min(index, len(self.clips)))
        self.clips[index:index] = clips

    def move(self, index: int, target: int) -> int:
        """Clip an die Lücke ``target`` (0 … len) verschieben; gibt den neuen Index zurück."""
        clip = self.clips.pop(index)
        if target > index:
            target -= 1
        target = max(0, min(target, len(self.clips)))
        self.clips.insert(target, clip)
        return target

    def move_many(self, indices: list[int], target: int) -> list[int]:
        """Mehrere Clips als Block an die Lücke ``target`` verschieben; gibt ihre neuen Indizes zurück."""
        indices = sorted(set(indices))
        block = [self.clips[i] for i in indices]
        for i in reversed(indices):
            self.clips.pop(i)
        target = max(0, min(target - sum(i < target for i in indices), len(self.clips)))
        self.clips[target:target] = block
        return list(range(target, target + len(block)))

    def remove(self, index: int) -> TimelineClip:
        return self.clips.pop(index)

    def trim_start(self, index: int, src_in: float) -> None:
        clip = self.clips[index]
        clip.src_in = max(0.0, min(src_in, clip.src_out - MIN_CLIP))

    def trim_end(self, index: int, src_out: float) -> None:
        clip = self.clips[index]
        limit = clip.source_duration if clip.source_duration else float("inf")
        clip.src_out = min(limit, max(src_out, clip.src_in + MIN_CLIP))

    def split(self, t: float) -> int | None:
        """Clip an Timeline-Zeit ``t`` teilen. Gibt den Index des zweiten Teils zurück."""
        hit = self.clip_at(t)
        if hit is None:
            return None
        index, offset = hit
        clip = self.clips[index]
        if offset < MIN_CLIP or clip.duration - offset < MIN_CLIP:
            return None
        cut = clip.src_in + offset
        second = TimelineClip(**{**clip.to_dict(), "src_in": cut}, path=clip.path)
        clip.src_out = cut
        self.clips.insert(index + 1, second)
        return index + 1

    # --- Projektdatei ----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": FORMAT_VERSION,
            "video_track": [c.to_dict() for c in self.clips],
            "music": asdict(self.music) if self.music else None,
            "original_volume": self.original_volume,
            "render_profile": self.render_profile,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Timeline:
        if data.get("version", 1) > FORMAT_VERSION:
            raise ValueError(translate("model", "The timeline comes from a newer FPVCut version."))
        music = data.get("music")
        return cls(
            clips=[TimelineClip(**c) for c in data.get("video_track", [])],
            music=MusicTrack(**music) if music else None,
            original_volume=data.get("original_volume", 1.0),
            render_profile=data.get("render_profile", "web"),
        )

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: str | Path) -> Timeline:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def copy(self) -> Timeline:
        """Tiefe Kopie, z. B. für Rückgängig; aufgelöste Pfade bleiben erhalten."""
        twin = Timeline.from_dict(self.to_dict())
        for mine, theirs in zip(self.clips, twin.clips):
            theirs.path = mine.path
        return twin
