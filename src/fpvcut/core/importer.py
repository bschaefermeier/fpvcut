"""Videos von der SD-Karte in die Bibliothek übernehmen: kopieren, prüfen, auf der Karte löschen.

Ziel ist ein Flugtag-Ordner ``YYYY-MM-DD_Spot`` in einem Bibliotheksordner. Neben den Videos
wandern gleichnamige Begleitdateien mit (z. B. ``.srt``/``.osd`` mit Telemetrie). Jede Datei wird
beim Kopieren gehasht, die Kopie danach von der Platte zurückgelesen und verglichen; gelöscht wird
auf der Karte nur, was so geprüft ist. Bis zur Prüfung heißt die Kopie ``….part``, ein Abbruch
hinterlässt also keine halben Videos in der Bibliothek.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import xxhash

from fpvcut.core.folder_names import FlightDay
from fpvcut.core.scanner import VIDEO_EXTENSIONS, iter_videos
from fpvcut.i18n import translate

CHUNK_SIZE = 8 * 1024 * 1024
PART_SUFFIX = ".part"
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

ProgressFn = Callable[[int, int, str], None]  # Bytes fertig, Bytes gesamt, aktuelle Datei


def folder_name(day: date, spot: str) -> str:
    """Ordnername im Schema ``YYYY-MM-DD_Spot``; Zeichen, die Windows nicht erlaubt, werden ersetzt."""
    spot = _INVALID.sub("-", spot).strip().rstrip(". ")
    return FlightDay("", day, spot).canonical_name or f"{day:%Y-%m-%d}"


def collect_files(folder: Path) -> list[Path]:
    """Videos im Ordner (mit Unterordnern) und ihre gleichnamigen Begleitdateien."""
    videos = list(iter_videos(folder))
    files = set(videos)
    for video in videos:
        for other in video.parent.iterdir():
            if (other.stem == video.stem and other.is_file() and not other.name.startswith("._")
                    and other.suffix.lower() not in VIDEO_EXTENSIONS):
                files.add(other)
    # Das Video vor seinen Begleitdateien: bekommt es im Ziel einen neuen Namen, folgen sie ihm.
    return sorted(files, key=lambda p: (p.parent.as_posix().lower(), p.stem.lower(),
                                        p.suffix.lower() not in VIDEO_EXTENSIONS, p.name.lower()))


def total_size(files: list[Path]) -> int:
    return sum(f.stat().st_size for f in files)


@dataclass
class ImportResult:
    copied: list[Path] = field(default_factory=list)  # Ziele neu kopierter Dateien
    already_there: list[Path] = field(default_factory=list)  # gleicher Inhalt lag schon im Ziel
    deleted: int = 0  # auf der Karte gelöscht
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False

    @property
    def verified(self) -> int:
        return len(self.copied) + len(self.already_there)

    @property
    def complete(self) -> bool:
        """Alles kopiert und geprüft (Voraussetzung fürs Auswerfen ohne Rückfrage)."""
        return not self.errors and not self.cancelled


class Cancelled(Exception):
    pass


def hash_file(path: Path, cancelled: Callable[[], bool] = lambda: False) -> str:
    h = xxhash.xxh3_128()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            if cancelled():
                raise Cancelled
            h.update(chunk)
    return h.hexdigest()


def _copy_hashed(source: Path, dest: Path, on_bytes: Callable[[int], None],
                 cancelled: Callable[[], bool]) -> str:
    h = xxhash.xxh3_128()
    with source.open("rb") as src, dest.open("wb") as dst:
        while chunk := src.read(CHUNK_SIZE):
            if cancelled():
                raise Cancelled
            h.update(chunk)
            dst.write(chunk)
            on_bytes(len(chunk))
        dst.flush()
        os.fsync(dst.fileno())
    shutil.copystat(source, dest)  # Aufnahmezeit behalten
    return h.hexdigest()


def _place(source: Path, target_dir: Path, name: str, cancelled: Callable[[], bool]) -> tuple[Path, bool]:
    """Ziel für ``source``: ``name``, bei Namensgleichheit ``name_1``, ``name_2`` …

    Gibt zusätzlich zurück, ob dort schon eine gleiche Kopie liegt (zweiter Import derselben Karte).
    """
    size = source.stat().st_size
    source_hash: str | None = None
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 0
    while True:
        dest = target_dir / (f"{stem}_{n}{suffix}" if n else name)
        n += 1
        if dest.exists():
            if os.path.samefile(dest, source):
                raise OSError(translate("importer", "source and target are the same file"))
            if dest.stat().st_size == size:
                source_hash = source_hash or hash_file(source, cancelled)
                if hash_file(dest, cancelled) == source_hash:
                    return dest, True
        elif not dest.with_name(dest.name + PART_SUFFIX).exists():
            return dest, False


def run_import(
    files: list[Path],
    target_dir: Path,
    delete_source: bool,
    progress: ProgressFn | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> ImportResult:
    result = ImportResult()
    total = total_size(files)
    done = 0
    verified: list[Path] = []  # Quellen, deren Kopie geprüft ist
    renamed_stems: dict[tuple[Path, str], str] = {}  # Begleitdateien folgen dem neuen Videonamen

    def tick(n: int, name: str) -> None:
        nonlocal done
        done += n
        if progress:
            progress(done, total, name)

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.errors.append(f"{target_dir}: {exc}")
        return result

    for source in files:
        if cancelled():
            result.cancelled = True
            break
        size = source.stat().st_size
        part: Path | None = None
        try:
            stem = renamed_stems.get((source.parent, source.stem), source.stem)
            dest, already_there = _place(source, target_dir, stem + source.suffix, cancelled)
            if dest.stem != stem:
                renamed_stems[(source.parent, source.stem)] = dest.stem
            if already_there:
                result.already_there.append(dest)
                verified.append(source)
                tick(size, source.name)
                continue
            part = dest.with_name(dest.name + PART_SUFFIX)
            if progress:
                progress(done, total, source.name)
            digest = _copy_hashed(source, part, lambda n: tick(n, source.name), cancelled)
            if part.stat().st_size != size or hash_file(part, cancelled) != digest:
                raise OSError(translate("importer", "copy differs from the original"))
            part.replace(dest)
            part = None
            result.copied.append(dest)
            verified.append(source)
        except Cancelled:
            result.cancelled = True
            break
        except OSError as exc:
            result.errors.append(f"{source.name}: {exc}")
        finally:
            if part is not None:
                part.unlink(missing_ok=True)

    if delete_source and not result.cancelled:
        for source in verified:
            try:
                source.unlink()
                result.deleted += 1
            except OSError as exc:
                result.errors.append(translate("importer", "{name}: not deleted on the card ({error})")
                                     .format(name=source.name, error=exc))
    return result
