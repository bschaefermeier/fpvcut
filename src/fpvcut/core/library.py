"""Bibliothek: SQLite-Datenbank mit Videos, Fundorten und Sichtungsstatus.

Videos werden über ihren Fingerprint identifiziert. Pfade sind nur zuletzt gesehene Fundorte;
eine Datei kann mehrere haben (Duplikate) oder vorübergehend keinen (fehlt).
Jede Instanz hält eine eigene SQLite-Verbindung; pro Thread eine eigene Instanz verwenden.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
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
    # Favoriten (Ausschnitte) und Tags. out_ms NULL = bis zum Ende des Videos.
    """
    CREATE TABLE clip (
        id INTEGER PRIMARY KEY,
        media_id INTEGER NOT NULL REFERENCES media_file(id) ON DELETE CASCADE,
        in_ms INTEGER NOT NULL,
        out_ms INTEGER,
        rating INTEGER,
        note TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL
    );
    CREATE INDEX clip_media ON clip(media_id);
    CREATE TABLE tag (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE
    );
    CREATE TABLE clip_tag (
        clip_id INTEGER NOT NULL REFERENCES clip(id) ON DELETE CASCADE,
        tag_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
        PRIMARY KEY (clip_id, tag_id)
    );
    """,
]


@dataclass
class RootFolder:
    id: int
    path: Path


@dataclass
class Clip:
    """Ein gespeicherter Ausschnitt eines Videos (oder das ganze Video) mit Tags."""

    id: int
    media_id: int
    in_ms: int
    out_ms: int | None
    note: str
    created_at: float
    tags: list[str] = field(default_factory=list)
    favorite: bool = False  # besonders gute Ausschnitte; in der Datenbank ``rating`` = 1

    @property
    def is_whole_video(self) -> bool:
        return self.in_ms == 0 and self.out_ms is None

    @property
    def in_s(self) -> float:
        return self.in_ms / 1000

    @property
    def out_s(self) -> float | None:
        return None if self.out_ms is None else self.out_ms / 1000


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
    fingerprint: str = ""
    clip_count: int = 0
    favorite_count: int = 0

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

    def last_seen(self, root_id: int) -> float:
        """Spätester Zeitpunkt, zu dem in diesem Ordner eine Datei gesehen wurde (0 ohne Dateien)."""
        row = self.conn.execute("SELECT MAX(last_seen) FROM media_path WHERE root_id = ?", (root_id,)).fetchone()
        return row[0] or 0.0

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
            """SELECT m.*, p.rel_path, p.missing, r.path AS root_path,
                      (SELECT COUNT(*) FROM clip c WHERE c.media_id = m.id) AS clip_count,
                      (SELECT COUNT(*) FROM clip c WHERE c.media_id = m.id AND c.rating > 0) AS favorite_count
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
                fingerprint=r["fingerprint"], clip_count=r["clip_count"],
                favorite_count=r["favorite_count"],
            )
            for r in rows
        ]

    def entry_for_media(self, media_id: int) -> LibraryEntry | None:
        return next((e for e in self.entries() if e.media_id == media_id), None)

    # --- Ausschnitte und Tags -------------------------------------------

    def add_clip(
        self, media_id: int, in_ms: int, out_ms: int | None, tags: list[str] = (), note: str = "",
        favorite: bool = False,
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO clip (media_id, in_ms, out_ms, rating, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (media_id, in_ms, out_ms, 1 if favorite else None, note, time.time()),
            )
            self._set_tags(cur.lastrowid, tags)
        return cur.lastrowid

    def update_clip(self, clip_id: int, tags: list[str], note: str, favorite: bool | None = None) -> None:
        with self.conn:
            self.conn.execute("UPDATE clip SET note = ? WHERE id = ?", (note, clip_id))
            if favorite is not None:
                self.set_favorite(clip_id, favorite)
            self._set_tags(clip_id, tags)

    def set_favorite(self, clip_id: int, favorite: bool) -> None:
        with self.conn:
            self.conn.execute("UPDATE clip SET rating = ? WHERE id = ?", (1 if favorite else None, clip_id))

    def delete_clip(self, clip_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM clip WHERE id = ?", (clip_id,))
            self.conn.execute("DELETE FROM tag WHERE id NOT IN (SELECT tag_id FROM clip_tag)")

    def clips_for(self, media_id: int | None) -> list[Clip]:
        """Ausschnitte eines Videos; ``None`` liefert alle Ausschnitte der Bibliothek."""
        rows = self.conn.execute(
            """SELECT c.*, GROUP_CONCAT(t.name, char(31)) AS tag_names
               FROM clip c
               LEFT JOIN clip_tag ct ON ct.clip_id = c.id
               LEFT JOIN tag t ON t.id = ct.tag_id
               WHERE ?1 IS NULL OR c.media_id = ?1
               GROUP BY c.id
               ORDER BY c.media_id, c.in_ms, c.id""",
            (media_id,),
        )
        return [
            Clip(
                id=r["id"], media_id=r["media_id"], in_ms=r["in_ms"], out_ms=r["out_ms"], note=r["note"],
                created_at=r["created_at"], favorite=bool(r["rating"]),
                tags=sorted(r["tag_names"].split(chr(31)), key=str.lower) if r["tag_names"] else [],
            )
            for r in rows
        ]

    def all_clips(self) -> list[tuple[Clip, LibraryEntry]]:
        """Alle Ausschnitte mit ihrem Video (für den Ausschnitt-Browser)."""
        entries = {e.media_id: e for e in self.entries()}
        return [(c, entries[c.media_id]) for c in self.clips_for(None) if c.media_id in entries]

    def tag_counts(self) -> list[tuple[str, int]]:
        rows = self.conn.execute(
            """SELECT t.name, COUNT(ct.clip_id) AS n FROM tag t JOIN clip_tag ct ON ct.tag_id = t.id
               GROUP BY t.id ORDER BY n DESC, t.name COLLATE NOCASE"""
        )
        return [(r["name"], r["n"]) for r in rows]

    def all_tags(self) -> list[str]:
        """Alle Tags, die meistbenutzten zuerst."""
        rows = self.conn.execute(
            """SELECT t.name FROM tag t LEFT JOIN clip_tag ct ON ct.tag_id = t.id
               GROUP BY t.id ORDER BY COUNT(ct.clip_id) DESC, t.name COLLATE NOCASE"""
        )
        return [r["name"] for r in rows]

    def _set_tags(self, clip_id: int, tags: list[str]) -> None:
        names = {t.strip().lower(): t.strip() for t in tags if t.strip()}.values()
        self.conn.execute("DELETE FROM clip_tag WHERE clip_id = ?", (clip_id,))
        for name in names:
            # Vorhandene Schreibweise beibehalten ("Crash" bleibt "Crash", auch wenn "crash" getippt wird).
            self.conn.execute("INSERT OR IGNORE INTO tag (name) VALUES (?)", (name,))
            tag_id = self.conn.execute("SELECT id FROM tag WHERE name = ?", (name,)).fetchone()["id"]
            self.conn.execute("INSERT OR IGNORE INTO clip_tag (clip_id, tag_id) VALUES (?, ?)", (clip_id, tag_id))
        self.conn.execute("DELETE FROM tag WHERE id NOT IN (SELECT tag_id FROM clip_tag)")
