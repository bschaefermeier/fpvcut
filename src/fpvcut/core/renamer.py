"""Umbenennungs-Helfer: Flugtag-Ordner ins Schema ``YYYY-MM-DD_Spot`` bringen.

Ablauf: ``plan_renames`` schlägt für jeden Ordner einen Namen vor, ``refresh_status`` prüft
die (evtl. von Hand geänderten) Namen auf Konflikte, ``apply_renames`` benennt um und
trägt die neuen Pfade in die Bibliothek ein. Favoriten hängen am Fingerprint, nicht am
Pfad, gehen also ohnehin nicht verloren; das Nachtragen spart nur den Neu-Scan.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath

from fpvcut.core.folder_names import _DAY_FIRST, _make_date, parse_folder_name
from fpvcut.core.scanner import VIDEO_EXTENSIONS

# Ab hier gelten Daten als plausibel für FPV-Aufnahmen.
EARLIEST_YEAR = 2010
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SCHEMA = re.compile(r"^\d{4}-\d{2}-\d{2}(?:_.+)?$")

OK, SAME, CHECK, CONFLICT, NO_DATE = "ok", "same", "check", "conflict", "nodate"


@dataclass
class RenameItem:
    root_id: int
    root: Path
    rel_path: str  # Ordner relativ zum Bibliotheksordner, mit "/"
    new_name: str
    warning: str = ""  # Hinweis aus der Datumserkennung
    status: str = OK
    note: str = ""
    checked: bool = True

    @property
    def old_name(self) -> str:
        return PurePosixPath(self.rel_path).name

    @property
    def parent_rel(self) -> str:
        parent = PurePosixPath(self.rel_path).parent.as_posix()
        return "" if parent == "." else parent

    @property
    def new_rel_path(self) -> str:
        return f"{self.parent_rel}/{self.new_name}" if self.parent_rel else self.new_name

    @property
    def path(self) -> Path:
        return self.root / self.rel_path

    @property
    def depth(self) -> int:
        return self.rel_path.count("/")


@dataclass
class RenameResult:
    done: list[RenameItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _date_warning(name: str, parsed: date, today: date) -> str:
    """Unklare Fälle: Datum in der Zukunft, sehr alt, oder auch anders herum lesbar."""
    if parsed > today:
        return f"Datum {parsed:%d.%m.%Y} liegt in der Zukunft"
    if parsed.year < EARLIEST_YEAR:
        return f"Datum {parsed:%d.%m.%Y} ist ungewöhnlich alt"
    if m := _DAY_FIRST.match(name):
        # 12_08_15 kann 12.08.2015 oder 15.08.2012 sein.
        alt = _make_date(m.group(1), m.group(2), m.group(3)) if len(m.group(3)) == 2 else None
        if alt and alt != parsed and EARLIEST_YEAR <= alt.year and alt <= today:
            return f"könnte auch {alt:%d.%m.%Y} sein"
    return ""


def _has_videos(names: list[str]) -> bool:
    return any(Path(n).suffix.lower() in VIDEO_EXTENSIONS and not n.startswith("._") for n in names)


def plan_renames(roots: list[tuple[int, Path]], today: date | None = None) -> list[RenameItem]:
    """Vorschläge für alle Ordner mit erkennbarem Datum und alle Video-Ordner ohne Datum.

    Unterordner eines Flugtags (z. B. ``2026-08-28_Wiese/raw``) bleiben unberührt.
    """
    today = today or date.today()
    items: list[RenameItem] = []
    for root_id, root in roots:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith((".", "$")))
            here = Path(dirpath)
            if here == root:
                continue
            rel = here.relative_to(root).as_posix()
            day = parse_folder_name(here.name)
            if day.date is not None:
                items.append(RenameItem(root_id, root, rel, day.canonical_name,
                                        warning=_date_warning(here.name.strip(), day.date, today)))
                continue
            in_flight_day = any(parse_folder_name(p).date for p in PurePosixPath(rel).parts[:-1])
            if not in_flight_day and _has_videos(filenames):
                items.append(RenameItem(root_id, root, rel, here.name, status=NO_DATE, checked=False))
    refresh_status(items)
    for item in items:
        item.checked = item.status == OK  # unklare Fälle muss man selbst anhaken
    return items


def refresh_status(items: list[RenameItem]) -> None:
    """Status nach (Hand-)Änderung der neuen Namen neu bestimmen."""
    targets: dict[tuple[int, str, str], int] = {}
    for item in items:
        if item.new_name != item.old_name:
            key = (item.root_id, item.parent_rel, item.new_name.casefold())
            targets[key] = targets.get(key, 0) + 1
    listings: dict[Path, set[str]] = {}
    for item in items:
        name = item.new_name
        parsed = parse_folder_name(item.old_name).date
        if name == item.old_name:
            item.status, item.note = (NO_DATE, "neuen Namen von Hand eintragen") if parsed is None \
                else (SAME, "passt schon")
        elif not name.strip() or _INVALID.search(name) or name.endswith((" ", ".")):
            item.status, item.note = CONFLICT, "ungültiger Ordnername"
        else:
            parent = item.path.parent
            if parent not in listings:
                try:
                    listings[parent] = {p.name.casefold() for p in parent.iterdir()}
                except OSError:
                    listings[parent] = set()
            exists = name.casefold() in listings[parent] and name.casefold() != item.old_name.casefold()
            if exists:
                item.status, item.note = CONFLICT, f"„{name}“ gibt es dort schon, z. B. _2 anhängen"
            elif targets.get((item.root_id, item.parent_rel, name.casefold()), 0) > 1:
                item.status, item.note = CONFLICT, "mehrere Ordner bekämen diesen Namen, z. B. _2 anhängen"
            elif not _SCHEMA.match(name):
                item.status, item.note = CHECK, "entspricht nicht dem Schema JJJJ-MM-TT_Spot"
            elif item.warning:
                item.status, item.note = CHECK, item.warning
            else:
                item.status, item.note = OK, ""
        if item.status not in (OK, CHECK):
            item.checked = False


def _move_paths(conn, root_id: int, old_rel: str, new_rel: str) -> None:
    """Pfade aller Dateien unter dem Ordner in der Bibliothek nachziehen."""
    like = old_rel.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"
    conn.execute(
        "UPDATE media_path SET rel_path = ? || substr(rel_path, ?) "
        "WHERE root_id = ? AND rel_path LIKE ? ESCAPE '\\'",
        (new_rel, len(old_rel) + 1, root_id, like),
    )


def apply_renames(items: list[RenameItem], conn=None) -> RenameResult:
    """Angehakte Ordner umbenennen, tiefste zuerst, damit die Pfade der übrigen stimmen."""
    result = RenameResult()
    for item in sorted((i for i in items if i.checked and i.status in (OK, CHECK)), key=lambda i: -i.depth):
        target = item.path.with_name(item.new_name)
        try:
            if target.exists() and target.name.casefold() != item.old_name.casefold():
                raise FileExistsError("Ziel existiert schon")
            item.path.rename(target)
        except OSError as exc:
            result.errors.append(f"{item.rel_path}: {exc.strerror or exc}")
            continue
        if conn is not None:
            _move_paths(conn, item.root_id, item.rel_path, item.new_rel_path)
        result.done.append(item)
    if conn is not None:
        conn.commit()
    return result


def undo_renames(done: list[RenameItem], conn=None) -> RenameResult:
    """Umbenennungen in umgekehrter Reihenfolge zurücknehmen."""
    # Flachste zuerst: Die gespeicherten Pfade tieferer Ordner enthalten noch die alten Elternnamen.
    reverse = [RenameItem(i.root_id, i.root, i.new_rel_path, i.old_name) for i in reversed(done)]
    result = RenameResult()
    for item in reverse:
        target = item.path.with_name(item.new_name)
        try:
            item.path.rename(target)
        except OSError as exc:
            result.errors.append(f"{item.rel_path}: {exc.strerror or exc}")
            continue
        if conn is not None:
            _move_paths(conn, item.root_id, item.rel_path, item.new_rel_path)
        result.done.append(item)
    if conn is not None:
        conn.commit()
    return result


def write_log(done: list[RenameItem], path: Path) -> None:
    """Protokoll alt → neu, damit sich eine Umbenennung auch später nachvollziehen lässt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = [{"root": str(i.root), "old": i.rel_path, "new": i.new_rel_path} for i in done]
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")

