"""Bibliotheksordner durchsuchen und mit der Datenbank abgleichen."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from fpvcut.core.fingerprint import fingerprint
from fpvcut.core.library import Library, RootFolder
from fpvcut.core.probe import MediaInfo
from fpvcut.i18n import translate

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".ts", ".mts", ".m2ts"}

ProbeFn = Callable[[Path], MediaInfo | None]
ProgressFn = Callable[[int, int, str], None]


@dataclass
class ScanResult:
    new: int = 0
    unchanged: int = 0
    rehashed: int = 0  # Pfad neu oder Datei geändert, aber Inhalt schon bekannt (verschoben/Duplikat)
    missing: int = 0  # Videos, die derzeit an keinem Fundort vorhanden sind
    errors: list[str] = field(default_factory=list)

    def merge(self, other: ScanResult) -> None:
        self.new += other.new
        self.unchanged += other.unchanged
        self.rehashed += other.rehashed
        self.errors += other.errors


def iter_videos(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        # Versteckte Ordner (z. B. .thumbnails) und Systemordner überspringen.
        dirnames[:] = sorted(d for d in dirnames if not d.startswith((".", "$")))
        for name in sorted(filenames):
            if Path(name).suffix.lower() in VIDEO_EXTENSIONS and not name.startswith("._"):
                yield Path(dirpath) / name


def scan_root(
    library: Library, root: RootFolder, probe: ProbeFn, progress: ProgressFn | None = None
) -> ScanResult:
    result = ScanResult()
    if not root.path.is_dir():
        result.errors.append(translate("scanner", "Folder not reachable: {path}").format(path=root.path))
        return result  # z. B. externe Platte nicht angesteckt: nichts als fehlend markieren

    # Die Windows-Uhr tickt nur alle ~15 ms: folgen zwei Scans schneller aufeinander, muss der
    # Start trotzdem nach allem liegen, was der vorige gesehen hat, sonst fällt nichts als fehlend auf.
    started = max(time.time(), library.last_seen(root.id) + 0.001)
    known = library.known_paths(root.id)
    files = list(iter_videos(root.path))
    for index, path in enumerate(files, start=1):
        rel_path = path.relative_to(root.path).as_posix()
        if progress:
            progress(index, len(files), rel_path)
        try:
            stat = path.stat()
            row = known.get(rel_path)
            now = max(time.time(), started)
            if row is not None and row["size"] == stat.st_size and row["mtime_ns"] == stat.st_mtime_ns:
                library.touch_path(row["id"], now)
                result.unchanged += 1
                continue
            fp = fingerprint(path)
            media_id = library.media_id_for(fp)
            if media_id is None:
                media_id = library.add_media(fp, stat.st_size, probe(path))
                result.new += 1
            else:
                result.rehashed += 1
            library.upsert_path(media_id, root.id, rel_path, stat.st_size, stat.st_mtime_ns, now)
        except OSError as exc:
            result.errors.append(f"{rel_path}: {exc}")
        finally:
            if index % 50 == 0:
                library.conn.commit()

    library.mark_unseen_missing(root.id, started)
    library.conn.commit()
    return result


def scan_library(library: Library, probe: ProbeFn, progress: ProgressFn | None = None) -> ScanResult:
    total = ScanResult()
    for root in library.roots():
        total.merge(scan_root(library, root, probe, progress))
    # Erst nach allen Ordnern aufräumen, damit Verschiebungen zwischen Ordnern erkannt werden.
    library.drop_stale_paths()
    library.conn.commit()
    total.missing = library.missing_count()
    return total
