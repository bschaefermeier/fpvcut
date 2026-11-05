"""Blackbox-Logs von Betaflight: auf dem Flugcontroller finden und den Flugtag daraus lesen.

Betaflight schreibt Logs entweder auf eine SD-Karte im Flugcontroller (``LOG00001.BFL`` …) oder in
den Flash-Speicher. Im Massenspeicher-Modus (Configurator → „Massenspeicher aktivieren“ bzw. ``msc``
im CLI) erscheint der Flugcontroller als Laufwerk; beim Flash-Speicher zeigt er jeden Log als
``BTFL_001.BBL`` … und zusätzlich alle zusammen als ``BTFL_ALL.BBL``. Den Sammel-Log braucht es
neben den einzelnen nicht, er wird dann übersprungen.

Kopiert wird mit :func:`fpvcut.core.importer.run_import` wie bei den Videos, Ziel ist der
Unterordner :data:`LOG_FOLDER` im Flugtag-Ordner.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from fpvcut.core.scanner import iter_files

LOG_EXTENSIONS = {".bbl", ".bfl"}
LOG_FOLDER = "Blackbox"  # Unterordner im Flugtag-Ordner
COMBINED_LOG = "btfl_all.bbl"  # alle Logs des Flash-Speichers in einer Datei
HEADER_BYTES = 64 * 1024  # die Kopfzeilen eines Logs stehen ganz am Anfang
_START = re.compile(rb"^H Log start datetime:(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", re.MULTILINE)


def collect_logs(folder: Path) -> list[Path]:
    """Blackbox-Logs im Ordner (mit Unterordnern); leere Dateien und der Sammel-Log fallen weg."""
    logs = [p for p in iter_files(folder, LOG_EXTENSIONS) if _size(p) > 0]
    singles = {p.parent for p in logs if p.name.lower() != COMBINED_LOG}
    return [p for p in logs if not (p.name.lower() == COMBINED_LOG and p.parent in singles)]


def has_logs(folder: Path) -> bool:
    """Liegen im Ordner oder eine Ebene darunter Logs? Schnell genug für das Nachsehen alle paar Sekunden."""

    def is_log(path: Path) -> bool:
        return path.suffix.lower() in LOG_EXTENSIONS and not path.name.startswith("._") and _size(path) > 0

    try:
        entries = list(folder.iterdir())
        if any(is_log(e) for e in entries):
            return True
        subfolders = [e for e in entries if e.is_dir() and not e.name.startswith((".", "$"))]
        return any(is_log(f) for sub in subfolders for f in sub.iterdir())
    except OSError:
        return False


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def log_start(path: Path) -> datetime | None:
    """Startzeit aus dem Kopf des (ersten) Logs in der Datei.

    ``None``, wenn sie fehlt oder die Uhr des Flugcontrollers nicht gestellt war: Betaflight
    schreibt dann das Jahr 0000 (bzw. 1970) hinein.
    """
    try:
        with path.open("rb") as f:
            head = f.read(HEADER_BYTES)
    except OSError:
        return None
    match = _START.search(head)
    if not match:
        return None
    try:
        start = datetime(*(int(g) for g in match.groups()))
    except ValueError:
        return None
    return start if start.year >= 2000 else None


def recording_day(logs: list[Path]) -> date | None:
    """Der Flugtag, wenn alle Logs mit gültiger Startzeit vom selben Tag sind."""
    days = {start.date() for start in map(log_start, logs) if start}
    return days.pop() if len(days) == 1 else None
