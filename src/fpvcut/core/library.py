"""Bibliothek: SQLite-Datenbank mit Videos, Fundorten und Sichtungsstatus.

Videos werden über ihren Fingerprint identifiziert. Pfade sind nur zuletzt gesehene Fundorte;
eine Datei kann mehrere haben (Duplikate) oder vorübergehend keinen (fehlt).
Jede Instanz hält eine eigene SQLite-Verbindung; pro Thread eine eigene Instanz verwenden.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from fpvcut.core.folder_names import FlightDay, flight_day_for
from fpvcut.core.probe import MediaInfo

# Jede Liste ist ein Migrationsschritt; neue Schritte nur anhängen, nie bestehende ändern.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE root_folder (
        id INTEGER PRIMARY KEY,
        path TEXT NOT NULL UNIQUE,
        added_at REAL NOT NULL
    );
    CREATE TABLE media_file (
        id INTEGER PRIMARY KEY,
        fingerprint TEXT NOT NULL UNIQUE,
        size INTEGER NOT NULL,
        duration REAL,
        width INTEGER,
        height INTEGER,
        fps REAL,
        vcodec TEXT,
        bit_depth INTEGER,
        acodec TEXT,
        probe_json TEXT,
        first_seen REAL NOT NULL,
        reviewed_at REAL
    );
    CREATE TABLE media_path (
        id INTEGER PRIMARY KEY,
        media_id INTEGER NOT NULL REFERENCES media_file(id) ON DELETE CASCADE,
        root_id INTEGER NOT NULL REFERENCES root_folder(id) ON DELETE CASCADE,
        rel_path TEXT NOT NULL,
        size INTEGER NOT NULL,
        mtime_ns INTEGER NOT NULL,
        last_seen REAL NOT NULL,
        missing INTEGER NOT NULL DEFAULT 0,
        UNIQUE (root_id, rel_path)
    );
    CREATE INDEX media_path_media ON media_path(media_id);
    """,
]


@dataclass
class RootFolder:
    id: int
    path: Path


@dataclass
class LibraryEntry:
    """Ein Video mit seinem (bevorzugten) Fundort, für die Anzeige."""

    media_id: int
    root_path: Path
    rel_path: str
    missing: bool
    size: int
    duration: float | None
    width: int | None
    height: int | None
    fps: float | None
    vcodec: str | None
    bit_depth: int | None
    acodec: str | None
    first_seen: float
    reviewed_at: float | None

    @property
    def path(self) -> Path:
        return self.root_path / self.rel_path

    @property
    def is_new(self) -> bool:
        return self.reviewed_at is None

    @property
    def flight_day(self) -> FlightDay:
        return flight_day_for(self.rel_path)


class Library:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def close(self) -> None:
        self.conn.close()

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for step, sql in enumerate(MIGRATIONS[version:], start=version + 1):
            with self.conn:
                self.conn.executescript(sql)
                self.conn.execute(f"PRAGMA user_version = {step}")

    # --- Bibliotheksordner ----------------------------------------------

    def add_root(self, path: str | Path) -> RootFolder:
        resolved = str(Path(path).resolve())
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO root_folder (path, added_at) VALUES (?, ?)", (resolved, time.time())
            )
        row = self.conn.execute("SELECT id, path FROM root_folder WHERE path = ?", (resolved,)).fetchone()
        return RootFolder(row["id"], Path(row["path"]))

    def roots(self) -> list[RootFolder]:
        rows = self.conn.execute("SELECT id, path FROM root_folder ORDER BY path")
        return [RootFolder(r["id"], Path(r["path"])) for r in rows]

    def remove_root(self, root_id: int) -> None:
        """Entfernt den Ordner aus der Bibliothek. Videos ohne Fundort bleiben samt Status erhalten."""
        with self.conn:
            self.conn.execute("DELETE FROM root_folder WHERE id = ?", (root_id,))

    # --- Für den Scanner -------------------------------------------------

    def known_paths(self, root_id: int) -> dict[str, sqlite3.Row]:
        rows = self.conn.execute(
            "SELECT id, media_id, rel_path, size, mtime_ns FROM media_path WHERE root_id = ?", (root_id,)
        )
        return {r["rel_path"]: r for r in rows}

    def media_id_for(self, fp: str) -> int | None:
        row = self.conn.execute("SELECT id FROM media_file WHERE fingerprint = ?", (fp,)).fetchone()
        return row["id"] if row else None

    def add_media(self, fp: str, size: int, info: MediaInfo | None) -> int:
        info = info or MediaInfo()
        cur = self.conn.execute(
            """INSERT INTO media_file (fingerprint, size, duration, width, height, fps, vcodec, bit_depth,
                                       acodec, probe_json, first_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fp, size, info.duration, info.width, info.height, info.fps, info.vcodec, info.bit_depth,
             info.acodec, json.dumps(info.raw) if info.raw else None, time.time()),
        )
        return cur.lastrowid

    def touch_path(self, path_id: int, now: float) -> None:
        self.conn.execute("UPDATE media_path SET last_seen = ?, missing = 0 WHERE id = ?", (now, path_id))

    def upsert_path(self, media_id: int, root_id: int, rel_path: str, size: int, mtime_ns: int, now: float) -> None:
        self.conn.execute(
            """INSERT INTO media_path (media_id, root_id, rel_path, size, mtime_ns, last_seen, missing)
               VALUES (?, ?, ?, ?, ?, ?, 0)
               ON CONFLICT (root_id, rel_path) DO UPDATE SET
                   media_id = excluded.media_id, size = excluded.size, mtime_ns = excluded.mtime_ns,
                   last_seen = excluded.last_seen, missing = 0""",
            (media_id, root_id, rel_path, size, mtime_ns, now),
        )

    def mark_unseen_missing(self, root_id: int, scan_started: float) -> int:
        cur = self.conn.execute(
            "UPDATE media_path SET missing = 1 WHERE root_id = ? AND last_seen < ? AND missing = 0",
            (root_id, scan_started),
        )
        return cur.rowcount

    def drop_stale_paths(self) -> int:
        """Löscht fehlende Fundorte von Videos, die anderswo noch vorhanden sind (= verschoben)."""
        cur = self.conn.execute(
            """DELETE FROM media_path WHERE missing = 1 AND media_id IN (
                   SELECT media_id FROM media_path WHERE missing = 0)"""
        )
        return cur.rowcount

    def missing_count(self) -> int:
        return self.conn.execute(
            """SELECT COUNT(DISTINCT media_id) FROM media_path WHERE media_id NOT IN (
                   SELECT media_id FROM media_path WHERE missing = 0)"""
        ).fetchone()[0]

    # --- Sichtungsstatus -------------------------------------------------

    def set_reviewed(self, media_ids: list[int], reviewed: bool = True) -> None:
        stamp = time.time() if reviewed else None
        with self.conn:
            self.conn.executemany(
                "UPDATE media_file SET reviewed_at = ? WHERE id = ?", [(stamp, mid) for mid in media_ids]
            )

    # --- Abfragen für die Oberfläche ------------------------------------

    def entries(self) -> list[LibraryEntry]:
        """Alle Videos mit einem Fundort; vorhandene Fundorte haben Vorrang vor fehlenden."""
        rows = self.conn.execute(
            """SELECT m.*, p.rel_path, p.missing, r.path AS root_path
               FROM media_file m
               JOIN media_path p ON p.id = (
                   SELECT id FROM media_path WHERE media_id = m.id ORDER BY missing, last_seen DESC LIMIT 1)
               JOIN root_folder r ON r.id = p.root_id
               ORDER BY p.rel_path"""
        )
        return [
            LibraryEntry(
                media_id=r["id"], root_path=Path(r["root_path"]), rel_path=r["rel_path"],
                missing=bool(r["missing"]), size=r["size"], duration=r["duration"], width=r["width"],
                height=r["height"], fps=r["fps"], vcodec=r["vcodec"], bit_depth=r["bit_depth"],
                acodec=r["acodec"], first_seen=r["first_seen"], reviewed_at=r["reviewed_at"],
            )
            for r in rows
        ]
